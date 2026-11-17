"""Tareas programadas (BUILD_SPEC §3): `run_daily_jobs()`.

Se ejecuta de dos formas:
  * Celery beat (`sti.run_daily_jobs_task`, 06:00 America/Bogota) si hay `CELERY_BROKER_URL`.
  * Endpoint `POST /api/v1/admin/jobs/run-daily` con header `X-Jobs-Secret` (cron externo: GitHub Actions /
    Render Cron) — lo implementa el slice A llamando a `run_daily_jobs()`.

CONTRATO: cada job es una función ``(db: Session, hoy: date) -> int`` (cuántos registros afectó) y es IDEMPOTENTE
(puede correr varias veces al día; use `dedupe_key` en `notify`). `run_daily_jobs` los ejecuta en orden, aísla los
errores de cada uno y devuelve un resumen ``{nombre: {"afectados": n} | {"error": "..."}}``.

ESTADO: completo (slice A). Cada job devuelve int o dict `{"afectados": n, ...}`; `expire_exports` es del slice C1.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import session_scope
from app.models.academico import AsignacionDocente, CalendarioAcademico, Matricula, ProgramaAcademico
from app.models.base import utcnow
from app.models.consentimiento import AutorizacionFamiliar, SolicitudIngreso
from app.models.contexto import ContextoUniversitario
from app.models.enums import EstadoAutorizacionFamiliar, EstadoPlanEnum, EstadoTareaNegociacion, EstadoUsuario, Rol
from app.models.plan import AjusteRazonable, PlanMaarTea, TareaNegociacion
from app.models.sistema import EmailOutbox, Notificacion
from app.models.usuarios import Docente, Estudiante, PreferenciaSensorialUI, RefreshToken, Usuario
from app.services.messaging import push
from app.services.notifications import Evento, notify
from app.services.params import get_param
from app.services.tasks import task

logger = logging.getLogger("sti.jobs")


def purge_unconsented_accounts(db: Session, hoy: date) -> int:
    """Purga legal: cuentas de estudiante en PENDIENTE_CONSENTIMIENTO con más de N días (30) sin F0 firmado.

    Es la ÚNICA operación (con ESTADO_PLAN) autorizada a borrar físicamente: activa `allow_hard_delete` en la
    sesión. Solo toca cuentas sin ningún dato pedagógico (nunca firmaron F0, por lo que no hay F1–F10).
    """
    dias = int(get_param(db, "dias_purga_sin_consentimiento", 30))
    limite = utcnow() - timedelta(days=dias)
    users = db.scalars(
        select(Usuario).where(
            Usuario.rol == Rol.ESTUDIANTE,
            Usuario.estado == EstadoUsuario.PENDIENTE_CONSENTIMIENTO,
            Usuario.created_at < limite,
        )
    ).all()
    purgados = 0
    db.info["allow_hard_delete"] = True
    try:
        for u in users:
            est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == u.id))
            # Salvaguarda: si por algún motivo existe consentimiento firmado, no se purga.
            from app.core.permissions import student_has_consent

            if est is not None and student_has_consent(db, est.id):
                continue
            db.execute(update(SolicitudIngreso).where(SolicitudIngreso.usuario_creado_id == u.id).values(usuario_creado_id=None))
            db.execute(delete(RefreshToken).where(RefreshToken.usuario_id == u.id))
            db.execute(delete(Notificacion).where(Notificacion.usuario_id == u.id))
            db.execute(delete(EmailOutbox).where(EmailOutbox.usuario_id == u.id))
            db.execute(delete(PreferenciaSensorialUI).where(PreferenciaSensorialUI.usuario_id == u.id))
            if est is not None:
                db.execute(delete(Matricula).where(Matricula.estudiante_id == est.id))
                db.delete(est)
            audit.log(db, None, audit.Accion.PURGA_CUENTAS_SIN_CONSENTIMIENTO, "usuario", u.id,
                      {"dias": dias}, actor_rol="SISTEMA")
            db.delete(u)
            purgados += 1
        db.flush()
    finally:
        db.info.pop("allow_hard_delete", None)
    return purgados


def _bienestar_ids(db: Session) -> list[int]:
    return list(db.scalars(select(Usuario.id).where(Usuario.rol == Rol.BIENESTAR, Usuario.estado == EstadoUsuario.ACTIVO)))


def _admin_ids(db: Session) -> list[int]:
    return list(db.scalars(select(Usuario.id).where(Usuario.rol == Rol.ADMIN, Usuario.estado == EstadoUsuario.ACTIVO)))


def _calendarios_activos(db: Session) -> list[CalendarioAcademico]:
    return list(db.scalars(select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True))))


def _ya_notificado(db: Session, key: str) -> bool:
    return bool(
        db.scalar(select(Notificacion.id).where(Notificacion.dedupe_key == key).limit(1))
        or db.scalar(select(EmailOutbox.id).where(EmailOutbox.dedupe_key == key).limit(1))
    )


def _notify_new(db: Session, evento: Evento, user_ids: list[int], payload: dict, key: str) -> int:
    """Notifica solo a quien aún no recibió `key` (idempotente). Devuelve cuántos destinatarios nuevos hubo."""
    nuevos = [u for u in dict.fromkeys(user_ids) if not _ya_notificado(db, f"{key}:u{u}")]
    if nuevos:
        notify(db, evento, nuevos, payload, dedupe_key=key)
    return len(nuevos)


def _planes_vigentes_de_calendario(db: Session, cal: CalendarioAcademico) -> list[PlanMaarTea]:
    stmt = select(PlanMaarTea).join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id).where(
        PlanMaarTea.estado.in_([EstadoPlanEnum.APROBADO, EstadoPlanEnum.IMPLEMENTACION, EstadoPlanEnum.SEGUIMIENTO])
    )
    if cal.programa_id is not None:
        stmt = stmt.where(Estudiante.programa_id == cal.programa_id)
    return list(db.scalars(stmt))


def _docentes_responsables(db: Session, planes: list[PlanMaarTea]) -> set[int]:
    ids = [p.id for p in planes]
    if not ids:
        return set()
    out: set[int] = set()
    for aj in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id.in_(ids))):
        if aj.responsable_id:
            out.add(aj.responsable_id)
        if aj.asignatura_id:
            out.update(db.scalars(
                select(Docente.usuario_id).join(AsignacionDocente, AsignacionDocente.docente_id == Docente.id)
                .where(AsignacionDocente.asignatura_id == aj.asignatura_id)
            ))
    return {u for u in out if (usr := db.get(Usuario, u)) is not None and str(usr.estado) == EstadoUsuario.ACTIVO}


def send_cut_reminders(db: Session, hoy: date) -> dict:
    """Recordatorios de corte C1/C2/C3: 7 días antes por correo y 1 día antes por push (in-app), a Bienestar,
    Estudiantes con plan vigente y Docentes responsables. Idempotente por corte+semestre+programa+usuario+tipo."""
    d_mail = int(get_param(db, "dias_recordatorio_corte_email", 7))
    d_push = int(get_param(db, "dias_recordatorio_corte_push", 1))
    enviados = 0
    detalle: dict[str, int] = {}
    for cal in _calendarios_activos(db):
        planes = None
        for corte, fecha in (("C1", cal.fecha_c1), ("C2", cal.fecha_c2), ("C3", cal.fecha_c3)):
            dias = (fecha - hoy).days
            if dias == d_mail:
                evento, sufijo = Evento.RECORDATORIO_CORTE_7D, "7d"
            elif dias == d_push:
                evento, sufijo = Evento.RECORDATORIO_CORTE_1D, "1d"
            else:
                continue
            if planes is None:
                planes = _planes_vigentes_de_calendario(db, cal)
            est_users = [e.usuario_id for e in db.scalars(select(Estudiante).where(
                Estudiante.id.in_([p.estudiante_id for p in planes] or [-1])))]
            est_users = [u for u in est_users if (usr := db.get(Usuario, u)) and str(usr.estado) == EstadoUsuario.ACTIVO]
            key = f"corte:{corte}:{cal.semestre_academico}:{cal.programa_id or 'all'}:{sufijo}"
            base = {"corte": corte, "fecha_corte": fecha.isoformat(), "semestre": cal.semestre_academico}
            n = 0
            for ids, enlace in (
                (_bienestar_ids(db), "/bienestar/seguimiento"),
                (est_users, "/estudiante/seguimiento"),
                (sorted(_docentes_responsables(db, planes)), "/docente/ajustes"),
            ):
                n += _notify_new(db, evento, ids, {**base, "enlace": enlace}, key)
            enviados += n
            detalle[f"{corte}_{sufijo}"] = detalle.get(f"{corte}_{sufijo}", 0) + n
    return {"afectados": enviados, **detalle}


def start_of_semester_f3_pending(db: Session, hoy: date) -> dict:
    """Al iniciar el semestre (ventana configurable) avisa a Bienestar que hay estudiantes con F3 pendiente."""
    ventana = int(get_param(db, "dias_ventana_f3_inicio_semestre", 14))
    notificados = pendientes_total = 0
    for cal in _calendarios_activos(db):
        if not (cal.fecha_inicio <= hoy <= cal.fecha_inicio + timedelta(days=ventana)):
            continue
        stmt = select(Estudiante.id).join(Usuario, Usuario.id == Estudiante.usuario_id).where(
            Usuario.estado == EstadoUsuario.ACTIVO,
            ~Estudiante.id.in_(select(ContextoUniversitario.estudiante_id).where(
                ContextoUniversitario.semestre_academico == cal.semestre_academico)),
        )
        if cal.programa_id is not None:
            stmt = stmt.where(Estudiante.programa_id == cal.programa_id)
        pendientes = len(list(db.scalars(stmt)))
        if not pendientes:
            continue
        pendientes_total += pendientes
        key = f"f3:{cal.semestre_academico}:{cal.programa_id or 'all'}"
        notificados += _notify_new(db, Evento.INICIO_SEMESTRE_F3_PENDIENTE, _bienestar_ids(db),
                                   {"semestre": cal.semestre_academico, "enlace": "/bienestar/estudiantes"}, key)
    return {"afectados": notificados, "estudiantes_pendientes": pendientes_total}


def practice_semester_alert(db: Session, hoy: date) -> dict:
    """Alerta a Bienestar cuando un estudiante está en el semestre de prácticas de su programa (una vez por semestre)."""
    alertas = 0
    for cal in _calendarios_activos(db):
        inicio = cal.fecha_inicio_practicas or cal.fecha_inicio
        if not (inicio <= hoy <= cal.fecha_fin):
            continue
        stmt = (
            select(Estudiante, Usuario).join(Usuario, Usuario.id == Estudiante.usuario_id)
            .join(ProgramaAcademico, ProgramaAcademico.id == Estudiante.programa_id)
            .where(Usuario.estado == EstadoUsuario.ACTIVO, Estudiante.semestre_actual == ProgramaAcademico.semestre_practicas)
        )
        if cal.programa_id is not None:
            stmt = stmt.where(Estudiante.programa_id == cal.programa_id)
        for est, usr in db.execute(stmt).all():
            destinos = [est.bienestar_asignado_id] if est.bienestar_asignado_id else _bienestar_ids(db)
            alertas += _notify_new(
                db, Evento.SEMESTRE_PRACTICAS, destinos,
                {"estudiante_nombre": usr.nombre_completo, "enlace": f"/bienestar/estudiantes/{est.id}"},
                f"practicas:{cal.semestre_academico}:e{est.id}",
            )
    return {"afectados": alertas}


def expire_invitations(db: Session, hoy: date) -> dict:
    """Invitaciones vencidas: limpia el token expirado de cuentas sin activar y avisa (Bienestar: estudiantes;
    Admin: demás roles). Autorizaciones familiares con `expira_at` vencida pasan a EXPIRADA."""
    ahora = utcnow()
    vencidos = db.scalars(select(Usuario).where(
        Usuario.activation_token_hash.is_not(None), Usuario.activation_expires_at < ahora, Usuario.password_hash.is_(None),
        Usuario.estado.in_([EstadoUsuario.PENDIENTE_ACTIVACION, EstadoUsuario.PENDIENTE_CONSENTIMIENTO]),
    )).all()
    est_n = otros_n = 0
    for u in vencidos:
        u.activation_token_hash = None
        if str(u.rol) == Rol.ESTUDIANTE:
            est_n += 1
        else:
            otros_n += 1
    if est_n:
        push(db, _bienestar_ids(db), tipo="INVITACION_VENCIDA", titulo="Invitaciones de estudiantes vencidas",
             mensaje=f"{est_n} invitación(es) de estudiantes venció (72 h) sin activarse. Reenvíe la invitación desde Usuarios.",
             enlace="/bienestar/estudiantes", dedupe_key=f"inv_vencidas:est:{hoy.isoformat()}")
    if otros_n:
        push(db, _admin_ids(db), tipo="INVITACION_VENCIDA", titulo="Invitaciones de usuarios vencidas",
             mensaje=f"{otros_n} invitación(es) venció sin activarse. Reenvíela desde Usuarios.",
             enlace="/admin/usuarios", dedupe_key=f"inv_vencidas:otros:{hoy.isoformat()}")
    expiradas = 0
    for a in db.scalars(select(AutorizacionFamiliar).where(
        AutorizacionFamiliar.expira_at.is_not(None), AutorizacionFamiliar.expira_at < ahora,
        AutorizacionFamiliar.estado.in_([EstadoAutorizacionFamiliar.PENDIENTE, EstadoAutorizacionFamiliar.VIGENTE]),
    )):
        a.estado = EstadoAutorizacionFamiliar.EXPIRADA
        expiradas += 1
    db.flush()
    return {"afectados": est_n + otros_n + expiradas, "invitaciones_estudiantes": est_n, "invitaciones_otros": otros_n,
            "autorizaciones_expiradas": expiradas}


def stalled_negotiations(db: Session, hoy: date) -> dict:
    """Planes con negociación sin movimiento por más de N días: recordatorio semanal a Bienestar."""
    dias = int(get_param(db, "dias_negociacion_estancada", 7))
    limite = utcnow() - timedelta(days=dias)
    planes: set[int] = set(db.scalars(select(TareaNegociacion.plan_id).where(
        TareaNegociacion.estado.in_([EstadoTareaNegociacion.ABIERTA, EstadoTareaNegociacion.EN_CICLO]),
        TareaNegociacion.updated_at < limite)))
    planes.update(db.scalars(select(PlanMaarTea.id).where(
        PlanMaarTea.estado == EstadoPlanEnum.EN_NEGOCIACION, PlanMaarTea.updated_at < limite)))
    semana = hoy.isocalendar()
    n = 0
    for pid in sorted(planes):
        n += push(db, _bienestar_ids(db), tipo="NEGOCIACION_ESTANCADA", titulo="Negociación del plan sin movimiento",
                  mensaje=f"Hay una negociación del Plan MAAR-TEA con más de {dias} días sin avances. Retómela con el estudiante.",
                  enlace=f"/bienestar/planes/{pid}", dedupe_key=f"negociacion_estancada:{pid}:{semana[0]}-{semana[1]}")
    return {"afectados": n, "planes": len(planes)}


def expire_exports(db: Session, hoy: date) -> int:
    """Marca como EXPIRADA y borra de almacenamiento las exportaciones vencidas (implementada en services/exports.py)."""
    from app.services import exports

    return exports.expire_exports(db, hoy)


#: Orden de ejecución. El slice A puede añadir jobs aquí sin tocar el resto.
JOBS: list[tuple[str, Callable[[Session, date], int]]] = [
    ("recordatorios_corte", send_cut_reminders),
    ("inicio_semestre_f3", start_of_semester_f3_pending),
    ("semestre_practicas", practice_semester_alert),
    ("vencimiento_invitaciones", expire_invitations),
    ("negociaciones_estancadas", stalled_negotiations),
    ("vencimiento_exportaciones", expire_exports),
    ("purga_sin_consentimiento", purge_unconsented_accounts),
]


def run_daily_jobs(db: Session | None = None, hoy: date | None = None) -> dict:
    """Ejecuta todos los jobs diarios. Si no se pasa `db`, abre su propia sesión (Celery / cron)."""
    hoy = hoy or date.today()
    if db is None:
        with session_scope() as own:
            return run_daily_jobs(own, hoy)
    resumen: dict[str, dict] = {}
    for nombre, fn in JOBS:
        try:
            with db.begin_nested():
                res = fn(db, hoy)
                resumen[nombre] = {"afectados": int(res.get("afectados", 0)), **{k: v for k, v in res.items() if k != "afectados"}}                     if isinstance(res, dict) else {"afectados": int(res)}
        except Exception as exc:  # noqa: BLE001 - un job no debe tumbar a los demás
            logger.exception("Falló el job %s", nombre)
            resumen[nombre] = {"error": str(exc)[:300]}
    audit.log(db, None, "JOBS_DIARIOS_EJECUTADOS", "jobs", None,
              {"hoy": hoy.isoformat(), "resumen": resumen, "errores": sum(1 for v in resumen.values() if "error" in v)},
              actor_rol="SISTEMA")
    db.commit()
    return resumen


@task("run_daily_jobs_task")
def run_daily_jobs_task() -> dict:
    return run_daily_jobs()
