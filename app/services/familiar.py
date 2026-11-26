"""Familiar Autorizado (D9, HU-22/28, Ley 1996/2019): el Estudiante otorga/revoca; el Familiar solo LEE lo autorizado.

* Nunca se exponen: AQ-10, notas de continuidad, barreras, diagnostico ni justificaciones clinicas del plan.
* Revocar corta el acceso al instante: la autorizacion se marca REVOCADA (los chequeos de `permissions` la excluyen) y, si el
  familiar no tiene otras autorizaciones vigentes, su cuenta pasa a INACTIVO (`get_current_user` responde 403) y se cierran
  sus sesiones.
* `notificar_seguimiento(db, estudiante_id, corte, semestre)`: para que el slice de seguimiento avise a los familiares con
  el alcance NOTIFICACIONES.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.permissions import (
    Accion,
    Recurso,
    can,
    familiar_autorizaciones_stmt,
    student_has_consent,
)
from app.core.security import revoke_all_user_tokens
from app.models.base import utcnow
from app.models.caracterizacion import Caracterizacion, PerfilFortalezas
from app.models.consentimiento import AutorizacionFamiliar
from app.models.enums import (
    AlcanceFamiliar,
    EstadoAutorizacionFamiliar,
    EstadoUsuario,
    Rol,
)
from app.models.plan import AjusteRazonable, EstrategiaDua, FirmaPlan, PlanMaarTea
from app.models.seguimiento import Seguimiento
from app.models.usuarios import Estudiante, Usuario
from app.services.accounts import create_user, invite_user, normalize_email
from app.services.notifications import Evento, notify
from app.services.plan_states import ESTADOS_VIGENTES

_CLAVES = {"plan": AlcanceFamiliar.PLAN, "seguimiento": AlcanceFamiliar.SEGUIMIENTO,
           "caracterizacion": AlcanceFamiliar.CARACTERIZACION, "notificaciones": AlcanceFamiliar.NOTIFICACIONES}
_ETIQUETAS = {"plan": "el Plan MAAR-TEA", "seguimiento": "el seguimiento", "caracterizacion": "la caracterización (F1-F2)",
              "notificaciones": "avisos de seguimiento"}
_VIVAS = (EstadoAutorizacionFamiliar.VIGENTE, EstadoAutorizacionFamiliar.PENDIENTE)


# ----------------------------------------------------------------------------- helpers
def alcance_a_lista(alcance: dict[str, bool]) -> list[str]:
    return [_CLAVES[k].value for k, v in alcance.items() if v and k in _CLAVES]


def lista_a_alcance(lista: list[str] | None) -> dict[str, bool]:
    return {k: v.value in (lista or []) for k, v in _CLAVES.items()}


def _fin_de_dia(d: date | None) -> datetime | None:
    return datetime.combine(d, time(23, 59, 59), tzinfo=UTC) if d else None


def _estado_efectivo(a: AutorizacionFamiliar) -> str:
    if a.revocada_at is not None or str(a.estado) == EstadoAutorizacionFamiliar.REVOCADA:
        return "REVOCADA"
    if a.expira_at is not None and a.expira_at <= utcnow():
        return "EXPIRADA"
    return str(a.estado)


def _viva(a: AutorizacionFamiliar) -> bool:
    return _estado_efectivo(a) in ("VIGENTE", "PENDIENTE")


def _nuevo_codigo_vinculacion() -> str:
    """Código corto que el estudiante le entrega al familiar (alfabeto sin 0/O/1/I)."""
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def serializar_autorizacion(db: Session, a: AutorizacionFamiliar) -> dict[str, Any]:
    u = db.get(Usuario, a.familiar_usuario_id) if a.familiar_usuario_id else None
    return {
        "id": a.id, "familiar_nombre": a.familiar_nombre, "familiar_email": a.familiar_email, "parentesco": a.parentesco,
        "alcance": lista_a_alcance(a.alcance), "estado": _estado_efectivo(a),
        "cuenta_activada": bool(u and u.password_hash and str(u.estado) == EstadoUsuario.ACTIVO),
        "otorgada_at": a.otorgada_at, "vigencia_hasta": a.expira_at, "revocada_at": a.revocada_at,
        "motivo_revocacion": a.motivo_revocacion,
        "codigo_vinculacion": a.codigo_vinculacion if _estado_efectivo(a) == "PENDIENTE" else None,
    }


def _sincronizar_flag_familia(db: Session, est: Estudiante) -> None:
    vivas = db.scalars(select(AutorizacionFamiliar).where(AutorizacionFamiliar.estudiante_id == est.id)).all()
    est.familia_autoriza_participacion = any(_viva(a) for a in vivas)


# ----------------------------------------------------------------------------- Estudiante: otorgar / listar / editar / revocar
def listar(db: Session, est: Estudiante, incluir_revocadas: bool = False) -> list[dict[str, Any]]:
    filas = db.scalars(select(AutorizacionFamiliar).where(AutorizacionFamiliar.estudiante_id == est.id)
                       .order_by(AutorizacionFamiliar.id.desc())).all()
    out = [serializar_autorizacion(db, a) for a in filas]
    return out if incluir_revocadas else [a for a in out if a["estado"] in ("VIGENTE", "PENDIENTE")]


def get_autorizacion_or_404(db: Session, est: Estudiante, autorizacion_id: int) -> AutorizacionFamiliar:
    a = db.get(AutorizacionFamiliar, autorizacion_id)
    if a is None or a.estudiante_id != est.id:
        raise NotFound("No encontramos esa autorización.", "AUTORIZACION_NO_ENCONTRADA")
    return a


def otorgar(db: Session, est: Estudiante, estudiante_user: Usuario, body, request=None) -> AutorizacionFamiliar:
    email = normalize_email(body.email)
    if email == estudiante_user.email:
        raise Unprocessable("No puede autorizarse a sí mismo: use otro correo.", "CORREO_PROPIO")
    alcance = body.alcance.model_dump()
    if not any(alcance.values()):
        raise Unprocessable("Elija al menos un tipo de información que el familiar podrá ver.", "ALCANCE_VACIO")
    expira = _fin_de_dia(body.vigencia_hasta)
    if expira is not None and expira <= utcnow():
        raise Unprocessable("La fecha de vigencia debe ser posterior a hoy.", "VIGENCIA_INVALIDA")
    previas = db.scalars(select(AutorizacionFamiliar).where(
        AutorizacionFamiliar.estudiante_id == est.id, AutorizacionFamiliar.familiar_email == email)).all()
    if any(_viva(a) for a in previas):
        raise Conflict("Ya autorizó a esta persona. Edite su autorización o revóquela primero.", "AUTORIZACION_DUPLICADA")

    settings = get_settings()
    user = db.scalar(select(Usuario).where(Usuario.email == email))
    if user is None:
        if settings.email_activation_required:  # flujo por correo: se crea la cuenta y se invita
            user = create_user(db, email=email, nombre_completo=body.nombre, rol=Rol.FAMILIAR)
        # sin correo: la autorización queda PENDIENTE con un código de vinculación; el familiar se registra con él
    elif str(user.rol) != Rol.FAMILIAR:
        raise Conflict("Ese correo ya pertenece a otra cuenta del sistema que no es de familiar. Use otro correo.",
                       "CORREO_EN_USO")
    elif str(user.estado) == EstadoUsuario.INACTIVO:
        user.estado = EstadoUsuario.ACTIVO if user.password_hash else EstadoUsuario.PENDIENTE_ACTIVACION
    activado = user is not None and bool(user.password_hash) and str(user.estado) == EstadoUsuario.ACTIVO
    sin_correo = user is None  # no hay cuenta aún: se vincula con código al registrarse

    a = AutorizacionFamiliar(
        estudiante_id=est.id, familiar_usuario_id=user.id if user else None, familiar_nombre=body.nombre.strip(),
        familiar_email=email, parentesco=body.parentesco, alcance=alcance_a_lista(alcance),
        estado=EstadoAutorizacionFamiliar.VIGENTE if activado else EstadoAutorizacionFamiliar.PENDIENTE,
        codigo_vinculacion=_nuevo_codigo_vinculacion() if sin_correo else None,
        otorgada_at=utcnow(), expira_at=expira)
    db.add(a)
    db.flush()
    if user is not None:
        enlace = f"{settings.frontend_url.rstrip('/')}/familiar"
        if not activado:  # cuenta sin activar (flujo por correo): invitacion con token de activacion (72 h)
            raw = invite_user(db, user, actor=estudiante_user, request=request)
            enlace = f"{settings.frontend_url.rstrip('/')}{settings.activation_path}?token={raw}"
        notify(db, Evento.AUTORIZACION_FAMILIAR_INVITACION, [user], {
            "nombre": body.nombre, "estudiante_nombre": estudiante_user.nombre_completo,
            "alcance": ", ".join(_ETIQUETAS[k] for k, v in alcance.items() if v), "enlace_activacion": enlace})
    _sincronizar_flag_familia(db, est)
    audit.log(db, estudiante_user, audit.Accion.AUTORIZACION_FAMILIAR_OTORGADA, "autorizacion_familiar", a.id,
              {"alcance": a.alcance, "parentesco": body.parentesco, "vigencia_hasta": str(body.vigencia_hasta)},
              request=request, estudiante_id=est.id)
    return a


def actualizar(db: Session, est: Estudiante, a: AutorizacionFamiliar, body, actor: Usuario, request=None):
    if not _viva(a):
        raise Conflict("Esta autorización ya no está vigente; otorgue una nueva.", "AUTORIZACION_NO_VIGENTE")
    campos = body.model_fields_set
    if body.alcance is not None:
        merged = lista_a_alcance(a.alcance)
        merged.update({k: v for k, v in body.alcance.model_dump().items() if v is not None})
        if not any(merged.values()):
            raise Unprocessable("Debe quedar al menos un tipo de información. Para cortar todo el acceso, revoque.",
                                "ALCANCE_VACIO")
        a.alcance = alcance_a_lista(merged)
    if "nombre" in campos and body.nombre:
        a.familiar_nombre = body.nombre.strip()
    if "parentesco" in campos:
        a.parentesco = body.parentesco
    if "vigencia_hasta" in campos:
        nueva = _fin_de_dia(body.vigencia_hasta)
        if nueva is not None and nueva <= utcnow():
            raise Unprocessable("La fecha de vigencia debe ser posterior a hoy.", "VIGENCIA_INVALIDA")
        a.expira_at = nueva
    db.flush()
    audit.log(db, actor, "AUTORIZACION_FAMILIAR_MODIFICADA", "autorizacion_familiar", a.id, {"alcance": a.alcance},
              request=request, estudiante_id=est.id)
    return a


def revocar(db: Session, est: Estudiante, a: AutorizacionFamiliar, actor: Usuario, motivo: str | None = None,
            request=None) -> AutorizacionFamiliar:
    if a.revocada_at is not None:
        raise Conflict("Esta autorización ya fue revocada.", "AUTORIZACION_YA_REVOCADA")
    a.estado, a.revocada_at, a.motivo_revocacion = EstadoAutorizacionFamiliar.REVOCADA, utcnow(), motivo
    db.flush()
    fam = db.get(Usuario, a.familiar_usuario_id) if a.familiar_usuario_id else None
    if fam is not None:
        otras = db.scalars(select(AutorizacionFamiliar).where(
            AutorizacionFamiliar.familiar_usuario_id == fam.id, AutorizacionFamiliar.id != a.id)).all()
        if not any(_viva(o) for o in otras):  # sin otras autorizaciones: cuenta inactiva y sesiones cerradas
            fam.estado = EstadoUsuario.INACTIVO
            fam.activation_token_hash = None
            fam.activation_expires_at = None
            revoke_all_user_tokens(db, fam.id)
    _sincronizar_flag_familia(db, est)
    audit.log(db, actor, audit.Accion.AUTORIZACION_FAMILIAR_REVOCADA, "autorizacion_familiar", a.id,
              {"motivo": motivo}, request=request, estudiante_id=est.id)
    return a


# ----------------------------------------------------------------------------- Familiar: lectura
def _guardia(db: Session, user: Usuario, estudiante_id: int, recurso: Recurso) -> Estudiante:
    """403 uniforme (no 404) para no revelar que un estudiante existe. Exige autorizacion vigente con ese alcance + F0."""
    if not can(db, user, estudiante_id, recurso, Accion.LEER):
        raise Forbidden("No tiene autorización del estudiante para ver esta información.", "ACCESO_DENEGADO")
    if not student_has_consent(db, estudiante_id):
        raise Forbidden("El estudiante no tiene vigente su consentimiento informado; no se puede mostrar información.",
                        "ESTUDIANTE_SIN_CONSENTIMIENTO")
    return db.get(Estudiante, estudiante_id)


def _nombre_est(db: Session, est: Estudiante) -> dict[str, Any]:
    u = db.get(Usuario, est.usuario_id)
    return {"id": est.id, "nombre": u.nombre_completo if u else None}


def estudiantes_autorizados(db: Session, user: Usuario) -> list[dict[str, Any]]:
    out = []
    for a in db.scalars(familiar_autorizaciones_stmt(user).order_by(AutorizacionFamiliar.id)):
        est = db.get(Estudiante, a.estudiante_id)
        if est is None:
            continue
        out.append({"estudiante_id": est.id, "nombre": _nombre_est(db, est)["nombre"], "parentesco": a.parentesco,
                    "alcance": lista_a_alcance(a.alcance), "vigencia_hasta": a.expira_at, "otorgada_at": a.otorgada_at})
    return out


def _plan_vigente(db: Session, estudiante_id: int) -> PlanMaarTea | None:
    return db.scalar(select(PlanMaarTea).where(
        PlanMaarTea.estudiante_id == estudiante_id, PlanMaarTea.estado.in_(ESTADOS_VIGENTES))
        .order_by(PlanMaarTea.semestre_academico.desc(), PlanMaarTea.id.desc()))


def _acceso(db: Session, user: Usuario, est: Estudiante, recurso_txt: str, request=None) -> None:
    audit.log(db, user, "ACCESO_FAMILIAR_" + recurso_txt, "estudiante", est.id, None, request=request, estudiante_id=est.id)


def ver_plan(db: Session, user: Usuario, estudiante_id: int, request=None) -> dict[str, Any]:
    est = _guardia(db, user, estudiante_id, Recurso.PLAN)
    plan = _plan_vigente(db, est.id)
    if plan is None:
        raise NotFound("Todavía no hay un Plan MAAR-TEA aprobado para mostrar.", "PLAN_NO_DISPONIBLE")
    ajustes = db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id)
                         .order_by(AjusteRazonable.id)).all()
    estrategias = db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id).order_by(EstrategiaDua.id)).all()
    firmas = db.scalars(select(FirmaPlan).where(FirmaPlan.plan_id == plan.id, FirmaPlan.version == plan.version)).all()
    _acceso(db, user, est, "PLAN", request)
    return {
        "estudiante": _nombre_est(db, est),
        "plan": {
            "semestre": plan.semestre_academico, "estado": str(plan.estado), "version": plan.version,
            "vigencia_inicio": plan.vigencia_inicio, "vigencia_fin": plan.vigencia_fin,
            "fecha_aprobacion": plan.fecha_aprobacion, "resumen_ejecutivo": plan.resumen_ejecutivo,
            "ajustes": [{"id": a.id, "nombre_ajuste": a.nombre_ajuste, "descripcion": a.descripcion_ajuste,
                         "tipo_ajuste": str(a.tipo_ajuste), "frecuencia": a.frecuencia,
                         "indicador_efectividad": a.indicador_efectividad, "estado": str(a.estado),
                         "semaforo_actual": str(a.semaforo_actual) if a.semaforo_actual else None} for a in ajustes],
            "estrategias_dua": [{"id": e.id, "nombre_estrategia": e.nombre_estrategia, "descripcion": e.descripcion,
                                 "dimension_dua": str(e.dimension_dua),
                                 "estado_implementacion": str(e.estado_implementacion)} for e in estrategias],
            "firmas": [{"rol": str(f.rol_firmante), "firmado_at": f.firmado_at} for f in firmas],
        },
    }


def ver_seguimiento(db: Session, user: Usuario, estudiante_id: int, request=None) -> dict[str, Any]:
    est = _guardia(db, user, estudiante_id, Recurso.SEGUIMIENTO)
    plan = _plan_vigente(db, est.id)
    if plan is None:
        raise NotFound("Todavía no hay seguimiento para mostrar: el plan aún no está aprobado.", "PLAN_NO_DISPONIBLE")
    nombres = {a.id: a.nombre_ajuste for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id))}
    cortes = []
    for s in db.scalars(select(Seguimiento).where(Seguimiento.plan_id == plan.id).order_by(Seguimiento.corte)):
        cortes.append({
            "corte": str(s.corte), "fecha_seguimiento": s.fecha_seguimiento,
            "semaforo_estado": str(s.semaforo_estado) if s.semaforo_estado else None, "cerrado": s.cerrado,
            "ajustes": [{"nombre_ajuste": nombres.get(r.ajuste_id), "semaforo": str(r.semaforo) if r.semaforo else None,
                         "implementado": r.implementado} for r in s.registros_ajuste]})
    _acceso(db, user, est, "SEGUIMIENTO", request)
    return {"estudiante": _nombre_est(db, est), "semestre": plan.semestre_academico, "cortes": cortes}


def ver_caracterizacion(db: Session, user: Usuario, estudiante_id: int, request=None) -> dict[str, Any]:
    est = _guardia(db, user, estudiante_id, Recurso.CARACTERIZACION)
    car = db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == est.id)
                    .order_by(Caracterizacion.version.desc(), Caracterizacion.id.desc()))
    perfil = db.scalar(select(PerfilFortalezas).where(PerfilFortalezas.estudiante_id == est.id)
                       .order_by(PerfilFortalezas.version.desc(), PerfilFortalezas.id.desc()))
    audit.log(db, user, audit.Accion.ACCESO_CARACTERIZACION, "caracterizacion", car.id if car else None,
              {"via": "FAMILIAR"}, request=request, estudiante_id=est.id)
    f1 = None
    if car is not None:
        f1 = {
            "fecha_caracterizacion": car.fecha_caracterizacion, "resumen_ejecutivo": car.resumen_ejecutivo,
            "autodescripcion_estudiante": car.autodescripcion_estudiante,
            "comunicacion": [{"tipo": d.tipo_comunicacion, "descripcion": d.descripcion,
                              "fortalezas": d.fortalezas_comunicacion, "estrategias_favorables": d.estrategias_favorables}
                             for d in car.datos_comunicacion],
            "sensorial": [{"tipo": str(d.tipo_sensorial), "descripcion": d.descripcion_experiencia,
                           "estrategias_autoregulacion": d.estrategias_autoregulacion} for d in car.datos_sensoriales],
            "autonomia": [{"contexto": d.contexto_autonomia, "nivel": str(d.nivel_autonomia)}
                          for d in car.datos_autonomia],
            "preferencias": [{"tipo": d.tipo_preferencia, "descripcion": d.descripcion} for d in car.datos_preferencia],
        }
    f2 = None
    if perfil is not None:
        f2 = {
            "narrativa_fortalezas": perfil.narrativa_fortalezas, "narrativa_intereses": perfil.narrativa_intereses,
            "narrativa_estrategias": perfil.narrativa_estrategias,
            "fortalezas": [{"nombre": f.nombre_fortaleza, "descripcion": f.descripcion_detallada} for f in perfil.fortalezas],
            "intereses": [{"nombre": i.nombre_interes, "descripcion": i.descripcion} for i in perfil.intereses],
            "estrategias": [{"nombre": e.nombre_estrategia, "descripcion": e.descripcion} for e in perfil.estrategias],
        }
    return {"estudiante": _nombre_est(db, est), "caracterizacion": f1, "fortalezas": f2}


# ----------------------------------------------------------------------------- notificaciones (HU-28)
def familiares_para_notificar(db: Session, estudiante_id: int) -> list[Usuario]:
    out = []
    for a in db.scalars(select(AutorizacionFamiliar).where(AutorizacionFamiliar.estudiante_id == estudiante_id)):
        if _viva(a) and a.permite(AlcanceFamiliar.NOTIFICACIONES) and a.familiar_usuario_id:
            u = db.get(Usuario, a.familiar_usuario_id)
            if u is not None and str(u.estado) == EstadoUsuario.ACTIVO:
                out.append(u)
    return out


def notificar_seguimiento(db: Session, estudiante_id: int, corte: str, semestre: str) -> int:
    """Avisa a los familiares con alcance NOTIFICACIONES que se registro el seguimiento del `corte`. Sin commit."""
    est = db.get(Estudiante, estudiante_id)
    fams = familiares_para_notificar(db, estudiante_id)
    if not fams or est is None:
        return 0
    nombre = _nombre_est(db, est)["nombre"]
    notify(db, Evento.SEGUIMIENTO_FAMILIAR, fams,
           {"estudiante_nombre": nombre, "corte": corte, "semestre": semestre, "enlace": "/familiar"},
           dedupe_key=f"seg-fam:{estudiante_id}:{semestre}:{corte}")
    return len(fams)
