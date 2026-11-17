"""Notificaciones (M10): in-app (NOTIFICACION, "push") + correo (EMAIL_OUTBOX).

API principal::

    notify(db, Evento.AJUSTE_SEMAFORO_ROJO, destinatarios=[bienestar, coordinador, docente, estudiante_user],
           payload={"estudiante_nombre": "...", "ajuste": "...", "corte": "C2", "enlace": "/bienestar/planes/12"})

* `destinatarios`: objetos `Usuario` o ids. Se deduplican.
* `canales`: opcional; por defecto los del catálogo (columna "Canal" de §10 M10).
* NO hace commit: las filas se confirman con la transacción de negocio. Si hay SMTP configurado, el envío real
  se programa después del commit (`after_commit`) vía `tasks.enqueue`; sin SMTP el correo queda OMITIDO en outbox.
* Privacidad: las plantillas NO incluyen datos clínicos (puntaje AQ-10, diagnóstico, narrativas F1). Los
  `payload` deben contener solo nombres, ids, cortes y enlaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.models.enums import CanalNotificacion as Canal
from app.models.enums import EstadoEmail
from app.models.sistema import EmailOutbox, Notificacion
from app.models.usuarios import Usuario
from app.services import email as email_service
from app.services.tasks import enqueue, task

logger = logging.getLogger("sti.notifications")


class Evento(StrEnum):
    """Eventos de §10 M10 (+ eventos operativos de cuenta y exportación)."""

    CUENTA_CREADA = "CUENTA_CREADA"  # invitación con enlace de activación (72 h)
    CONSENTIMIENTO_PENDIENTE = "CONSENTIMIENTO_PENDIENTE"
    AQ10_POSITIVO = "AQ10_POSITIVO"
    RECORDATORIO_CORTE_7D = "RECORDATORIO_CORTE_7D"
    RECORDATORIO_CORTE_1D = "RECORDATORIO_CORTE_1D"
    AJUSTE_SEMAFORO_ROJO = "AJUSTE_SEMAFORO_ROJO"  # RF-39
    AJUSTE_SEMAFORO_AMARILLO = "AJUSTE_SEMAFORO_AMARILLO"  # tarea de concertación (RF-29)
    INASISTENCIA_UMBRAL = "INASISTENCIA_UMBRAL"
    PLAN_LISTO_FIRMA = "PLAN_LISTO_FIRMA"
    PLAN_FIRMADO_APROBADO = "PLAN_FIRMADO_APROBADO"
    INICIO_SEMESTRE_F3_PENDIENTE = "INICIO_SEMESTRE_F3_PENDIENTE"
    SEMESTRE_PRACTICAS = "SEMESTRE_PRACTICAS"
    NEGOCIACION_ESCALADA_COMITE = "NEGOCIACION_ESCALADA_COMITE"
    # operativos
    RECUPERACION_CONTRASENA = "RECUPERACION_CONTRASENA"
    SOLICITUD_INGRESO_NUEVA = "SOLICITUD_INGRESO_NUEVA"
    SOLICITUD_INGRESO_RESUELTA = "SOLICITUD_INGRESO_RESUELTA"
    AUTORIZACION_FAMILIAR_INVITACION = "AUTORIZACION_FAMILIAR_INVITACION"
    CONSENTIMIENTO_REVOCADO = "CONSENTIMIENTO_REVOCADO"
    EXPORTACION_LISTA = "EXPORTACION_LISTA"
    NOTA_CONTINUIDAD_PENDIENTE = "NOTA_CONTINUIDAD_PENDIENTE"
    F10_PENDIENTE_APROBACION = "F10_PENDIENTE_APROBACION"  # slice C3
    SEGUIMIENTO_FAMILIAR = "SEGUIMIENTO_FAMILIAR"  # slice C3 (HU-28)
    # slice B (F0 / ARCO)
    CONSENTIMIENTO_COPIA = "CONSENTIMIENTO_COPIA"
    ARCO_SOLICITUD_NUEVA = "ARCO_SOLICITUD_NUEVA"
    ARCO_SOLICITUD_RESUELTA = "ARCO_SOLICITUD_RESUELTA"


@dataclass(frozen=True)
class PlantillaEvento:
    titulo: str
    asunto: str
    cuerpo: str
    canales: tuple[Canal, ...]
    enlace_default: str | None = None
    guardar_payload: bool = True  # False cuando el payload lleva tokens (activación/recuperación)


_PUSH, _EMAIL = Canal.PUSH, Canal.EMAIL
_PIE = "\n\nSistema Tutor Inteligente (STI) - Universidad de Córdoba.\nSi tiene dudas, responda a Bienestar Universitario."

#: Variables disponibles en las plantillas: las claves del `payload` (las ausentes quedan vacías).
CATALOGO: dict[Evento, PlantillaEvento] = {
    Evento.CUENTA_CREADA: PlantillaEvento(
        titulo="Su cuenta fue creada",
        asunto="Active su cuenta en el STI",
        cuerpo=(
            "Hola {nombre}.\n\nSe creó su cuenta en el Sistema Tutor Inteligente (STI) con el rol {rol}.\n"
            "Para activarla, ingrese al siguiente enlace y elija su contraseña:\n{enlace_activacion}\n\n"
            "El enlace funciona durante {horas_validez} horas. Si no lo usa a tiempo, pida una nueva invitación."
            + _PIE
        ),
        canales=(_EMAIL,),
        guardar_payload=False,
    ),
    Evento.CONSENTIMIENTO_PENDIENTE: PlantillaEvento(
        titulo="Falta firmar su consentimiento informado",
        asunto="Pendiente: firme su consentimiento informado (F0)",
        cuerpo=(
            "Hola {nombre}.\n\nPara usar el STI necesitamos que lea y firme el consentimiento informado (F0). "
            "Allí le explicamos qué datos se recogen, quién los ve y cómo los protegemos. "
            "Puede retirar su consentimiento cuando quiera, sin consecuencias académicas.\n\n"
            "Ingrese aquí: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
        enlace_default="/estudiante/consentimiento",
    ),
    Evento.AQ10_POSITIVO: PlantillaEvento(
        titulo="Tamizaje AQ-10: se activó la ruta de caracterización",
        asunto="AQ-10 de {estudiante_nombre}: continuar con la caracterización (F1-F5)",
        cuerpo=(
            "El tamizaje AQ-10 de {estudiante_nombre} alcanzó o superó el punto de corte configurado. "
            "El sistema activó el flujo de caracterización formal (F1-F5).\n"
            "Recuerde: el AQ-10 es una herramienta de tamizaje, no un diagnóstico.\n"
            "Ver estudiante: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
    ),
    Evento.RECORDATORIO_CORTE_7D: PlantillaEvento(
        titulo="Faltan 7 días para el corte {corte}",
        asunto="Recordatorio: el corte {corte} es el {fecha_corte}",
        cuerpo=(
            "El corte {corte} del semestre {semestre} es el {fecha_corte} (faltan 7 días).\n"
            "Prepare el seguimiento (F8) de los ajustes del Plan MAAR-TEA: {enlace}" + _PIE
        ),
        canales=(_EMAIL,),
    ),
    Evento.RECORDATORIO_CORTE_1D: PlantillaEvento(
        titulo="Mañana es el corte {corte}",
        asunto="Mañana es el corte {corte}",
        cuerpo="Mañana es el corte {corte} ({fecha_corte}). Complete el seguimiento: {enlace}",
        canales=(_PUSH,),
    ),
    Evento.AJUSTE_SEMAFORO_ROJO: PlantillaEvento(
        titulo="Ajuste en ROJO: requiere rediseño",
        asunto="Alerta: un ajuste quedó en rojo ({corte})",
        cuerpo=(
            "El ajuste «{ajuste}» del Plan MAAR-TEA quedó en ROJO en el corte {corte}: no está funcionando "
            "o genera nuevas dificultades. Se requiere rediseñarlo antes de continuar.\nVer el plan: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
    ),
    Evento.AJUSTE_SEMAFORO_AMARILLO: PlantillaEvento(
        titulo="Ajuste en AMARILLO: concertar cambios",
        asunto="Un ajuste quedó en amarillo ({corte}): concerten antes del siguiente corte",
        cuerpo=(
            "El ajuste «{ajuste}» quedó en AMARILLO en el corte {corte} (efectividad parcial). "
            "Hay una tarea de concertación entre Bienestar y el estudiante antes del siguiente corte: {enlace}" + _PIE
        ),
        canales=(_PUSH,),
    ),
    Evento.INASISTENCIA_UMBRAL: PlantillaEvento(
        titulo="Inasistencia sobre el umbral",
        asunto="Alerta de inasistencia: {estudiante_nombre} ({porcentaje}%)",
        cuerpo=(
            "{estudiante_nombre} supera el umbral de inasistencia ({umbral}%): lleva {porcentaje}%.\n"
            "Revise el caso: {enlace}" + _PIE
        ),
        canales=(_EMAIL,),
    ),
    Evento.PLAN_LISTO_FIRMA: PlantillaEvento(
        titulo="Plan MAAR-TEA listo para firma",
        asunto="El Plan MAAR-TEA está listo para su firma",
        cuerpo="El Plan MAAR-TEA (versión {version}) está listo para su revisión y firma digital: {enlace}" + _PIE,
        canales=(_PUSH, _EMAIL),
    ),
    Evento.PLAN_FIRMADO_APROBADO: PlantillaEvento(
        titulo="Plan MAAR-TEA firmado y aprobado",
        asunto="El Plan MAAR-TEA fue firmado y aprobado",
        cuerpo="El Plan MAAR-TEA (versión {version}) quedó firmado por todos y aprobado. Puede consultarlo: {enlace}" + _PIE,
        canales=(_EMAIL,),
    ),
    Evento.INICIO_SEMESTRE_F3_PENDIENTE: PlantillaEvento(
        titulo="Inicio de semestre: F3 pendiente",
        asunto="Inicio del semestre {semestre}: hay F3 (contexto) pendientes",
        cuerpo="Inició el semestre {semestre}. Hay estudiantes con el análisis de contexto (F3) pendiente: {enlace}" + _PIE,
        canales=(_EMAIL,),
    ),
    Evento.SEMESTRE_PRACTICAS: PlantillaEvento(
        titulo="Semestre de prácticas: revisar el plan",
        asunto="{estudiante_nombre} inicia el semestre de prácticas",
        cuerpo=(
            "{estudiante_nombre} inicia el semestre de prácticas. Revise su Plan MAAR-TEA pensando en los escenarios "
            "de práctica clínica o de salud pública: {enlace}" + _PIE
        ),
        canales=(_EMAIL,),
    ),
    Evento.NEGOCIACION_ESCALADA_COMITE: PlantillaEvento(
        titulo="Desacuerdo escalado al Comité de Inclusión",
        asunto="Desacuerdo sobre un ajuste: pasó al Comité de Inclusión",
        cuerpo=(
            "Tras {ciclos} ciclos de negociación no hubo acuerdo sobre el ajuste «{ajuste}». "
            "El caso fue escalado al Comité de Inclusión institucional: {enlace}" + _PIE
        ),
        canales=(_EMAIL,),
    ),
    Evento.RECUPERACION_CONTRASENA: PlantillaEvento(
        titulo="Recuperación de contraseña",
        asunto="Restablezca su contraseña del STI",
        cuerpo=(
            "Recibimos una solicitud para restablecer su contraseña.\nIngrese aquí: {enlace_recuperacion}\n"
            "El enlace funciona durante {horas_validez} horas. Si usted no lo pidió, ignore este mensaje." + _PIE
        ),
        canales=(_EMAIL,),
        guardar_payload=False,
    ),
    Evento.SOLICITUD_INGRESO_NUEVA: PlantillaEvento(
        titulo="Nueva solicitud de ingreso",
        asunto="Nueva solicitud de ingreso al STI",
        cuerpo="Hay una nueva solicitud de ingreso (Vía 2) pendiente de revisión: {enlace}" + _PIE,
        canales=(_PUSH,),
        enlace_default="/bienestar/solicitudes",
    ),
    Evento.SOLICITUD_INGRESO_RESUELTA: PlantillaEvento(
        titulo="Respuesta a su solicitud de ingreso",
        asunto="Respuesta a su solicitud de ingreso al STI",
        cuerpo="{mensaje}" + _PIE,
        canales=(_EMAIL,),
    ),
    Evento.AUTORIZACION_FAMILIAR_INVITACION: PlantillaEvento(
        titulo="Autorización de acceso familiar",
        asunto="{estudiante_nombre} le autorizó ver información en el STI",
        cuerpo=(
            "Hola {nombre}.\n\n{estudiante_nombre} le autorizó acceso de solo lectura a: {alcance}.\n"
            "Active su cuenta aquí: {enlace_activacion}\nLa persona puede revocar este permiso cuando quiera." + _PIE
        ),
        canales=(_EMAIL,),
        guardar_payload=False,
    ),
    Evento.CONSENTIMIENTO_REVOCADO: PlantillaEvento(
        titulo="Consentimiento revocado",
        asunto="Un estudiante revocó su consentimiento",
        cuerpo=(
            "Un estudiante revocó su consentimiento (F0). Su cuenta se inactivó y sus datos se archivaron "
            "conforme a la Ley 1581 de 2012: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
    ),
    Evento.EXPORTACION_LISTA: PlantillaEvento(
        titulo="Su exportación está lista",
        asunto="Su exportación está lista",
        cuerpo="La exportación «{nombre_archivo}» ya está lista para descargar: {enlace}" + _PIE,
        canales=(_PUSH,),
    ),
    Evento.NOTA_CONTINUIDAD_PENDIENTE: PlantillaEvento(
        titulo="Hay una nota de continuidad para aprobar",
        asunto="Revise y apruebe su nota de continuidad",
        cuerpo=(
            "Hay una nota de continuidad institucional (F10) pendiente. Solo se compartirá con nuevos docentes o "
            "profesionales si usted la aprueba: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
    ),
    # --- slice B ---
    Evento.CONSENTIMIENTO_COPIA: PlantillaEvento(
        titulo="Copia de su consentimiento informado",
        asunto="Copia de su consentimiento informado (F0) - STI",
        cuerpo=(
            "Hola {nombre}.\n\nGracias por firmar el consentimiento informado (F0). Esta es su copia.\n"
            "Versión del texto: {version_texto}. Firmado el {firmado_at}. Huella digital del texto (SHA-256): {texto_hash}.\n\n"
            "{texto_f0}\n\n"
            "Puede retirar su consentimiento cuando quiera, sin consecuencias académicas, desde: {enlace}" + _PIE
        ),
        canales=(_EMAIL,),
        enlace_default="/estudiante/derechos",
    ),
    Evento.ARCO_SOLICITUD_NUEVA: PlantillaEvento(
        titulo="Nueva solicitud de derechos sobre datos (ARCO)",
        asunto="Nueva solicitud ARCO ({tipo}) - plazo {fecha_limite}",
        cuerpo=(
            "Un estudiante radicó una solicitud de {tipo} sobre sus datos personales (Ley 1581 de 2012). "
            "La respuesta debe darse a más tardar el {fecha_limite}.\nGestionar: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
        enlace_default="/bienestar/arco",
    ),
    Evento.ARCO_SOLICITUD_RESUELTA: PlantillaEvento(
        titulo="Respondimos su solicitud sobre sus datos",
        asunto="Respuesta a su solicitud sobre sus datos personales",
        cuerpo=(
            "Hola {nombre}.\n\nSu solicitud de {tipo} fue atendida (estado: {estado}). "
            "Puede ver la respuesta aquí: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
        enlace_default="/estudiante/derechos",
    ),
    Evento.F10_PENDIENTE_APROBACION: PlantillaEvento(
        titulo="Hay un cierre de semestre (F10) para revisar",
        asunto="Revise y apruebe el cierre de su semestre (F10)",
        cuerpo=(
            "Bienestar dejó listo el cierre de su semestre (F10): qué apoyos continúan, su trayectoria y las notas "
            "de continuidad. Nada pasa al siguiente semestre sin su aprobación: {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
    ),
    Evento.SEGUIMIENTO_FAMILIAR: PlantillaEvento(
        titulo="Hay una novedad en el seguimiento",
        asunto="Novedad en el seguimiento de {estudiante_nombre}",
        cuerpo=(
            "{estudiante_nombre} autorizó que usted reciba avisos del seguimiento de su Plan MAAR-TEA. "
            "Se registró el seguimiento del corte {corte} ({semestre}). Puede consultarlo (solo lectura): {enlace}" + _PIE
        ),
        canales=(_PUSH, _EMAIL),
        enlace_default="/familiar",
    ),
}


class _SafeDict(dict):
    def __missing__(self, key):  # variable ausente -> vacío, nunca error
        return ""


def render(evento: Evento, payload: dict[str, Any] | None) -> tuple[str, str, str, str | None]:
    """Devuelve (titulo, asunto, cuerpo, enlace_relativo) con el payload aplicado.

    En el cuerpo del correo `{enlace}` se expande a URL absoluta del frontend; en la notificación in-app se guarda
    la ruta relativa para que el frontend navegue sin recargar.
    """
    p = CATALOGO[evento]
    data = _SafeDict(payload or {})
    enlace = data.get("enlace") or p.enlace_default
    if enlace and not str(enlace).startswith(("http://", "https://")):
        data["enlace"] = f"{get_settings().frontend_url.rstrip('/')}{enlace}"
    else:
        data["enlace"] = enlace or ""
    return p.titulo.format_map(data), p.asunto.format_map(data), p.cuerpo.format_map(data), (enlace or None)


def _resolve(db: Session, destinatarios: list[Usuario | int]) -> list[Usuario]:
    seen: dict[int, Usuario] = {}
    for d in destinatarios:
        if d is None:
            continue
        user = d if isinstance(d, Usuario) else db.get(Usuario, int(d))
        if user is not None and user.id not in seen:
            seen[user.id] = user
    return list(seen.values())


def notify(
    db: Session,
    evento: Evento,
    destinatarios: list[Usuario | int],
    payload: dict[str, Any] | None = None,
    canales: list[Canal] | tuple[Canal, ...] | None = None,
    *,
    dedupe_key: str | None = None,
) -> list[Notificacion]:
    """Crea NOTIFICACION (PUSH) y/o EMAIL_OUTBOX (EMAIL) por destinatario. No hace commit.

    `dedupe_key` (p. ej. ``"corte:C1:2026-II:7d:u12"``) evita duplicar la misma notificación PUSH/correo si el
    job diario corre varias veces: si ya existe una NOTIFICACION con esa clave para el usuario, se omite.
    """
    evento = Evento(evento)
    plantilla = CATALOGO[evento]
    canales = tuple(canales) if canales else plantilla.canales
    users = _resolve(db, destinatarios)
    creadas: list[Notificacion] = []
    outbox_rows: list[EmailOutbox] = []
    smtp = get_settings().smtp_configured
    enviados = 0

    for u in users:
        key = f"{dedupe_key}:u{u.id}" if dedupe_key else None
        if key and (
            db.scalar(select(Notificacion.id).where(Notificacion.dedupe_key == key).limit(1)) is not None
            or db.scalar(select(EmailOutbox.id).where(EmailOutbox.dedupe_key == key).limit(1)) is not None
        ):
            continue
        pl = dict(payload or {})
        pl.setdefault("nombre", u.nombre_completo)
        titulo, asunto, cuerpo, enlace = render(evento, pl)
        enviados += 1
        if Canal.PUSH in canales:
            notif = Notificacion(
                usuario_id=u.id, tipo=evento.value, titulo=titulo, mensaje=cuerpo.split(_PIE)[0], enlace=enlace,
                payload=(payload if plantilla.guardar_payload else None), dedupe_key=key,
            )
            db.add(notif)
            creadas.append(notif)
        if Canal.EMAIL in canales and u.email:
            row = EmailOutbox(
                usuario_id=u.id, destinatario_email=u.email, asunto=asunto, cuerpo_texto=cuerpo,
                evento=evento.value, estado=EstadoEmail.PENDIENTE, dedupe_key=key,
            )
            db.add(row)
            outbox_rows.append(row)
    db.flush()
    for row in outbox_rows:
        if not smtp:
            email_service.deliver(row)  # marca OMITIDO y escribe en logs
    db.flush()

    if enviados:
        audit.log(db, None, audit.Accion.NOTIFICACION_ENVIADA, "notificacion", None,
                  {"evento": evento.value, "destinatarios": enviados, "canales": [str(c) for c in canales]})
    if smtp and outbox_rows:
        _schedule_after_commit(db)
    return creadas


def _schedule_after_commit(db: Session) -> None:
    if db.info.get("_outbox_scheduled"):
        return
    db.info["_outbox_scheduled"] = True

    def _after(session):
        session.info.pop("_outbox_scheduled", None)
        enqueue(process_email_outbox_task)

    event.listen(db, "after_commit", _after, once=True)


@task("process_email_outbox_task")
def process_email_outbox_task() -> int:
    from app.core.db import session_scope

    with session_scope() as db:
        return email_service.process_outbox(db)


def get_notification_user_ids(db: Session, rol: str, *, programa_id: int | None = None) -> list[int]:
    """Utilidad para los slices: ids de usuarios ACTIVOS de un rol (opcionalmente de un programa)."""
    from app.models.enums import EstadoUsuario
    from app.models.usuarios import CoordinadorPrograma, Docente, Estudiante

    stmt = select(Usuario.id).where(Usuario.rol == rol, Usuario.estado == EstadoUsuario.ACTIVO)
    if programa_id is not None:
        if rol == "DOCENTE":
            stmt = stmt.join(Docente, Docente.usuario_id == Usuario.id).where(Docente.programa_id == programa_id)
        elif rol == "ESTUDIANTE":
            stmt = stmt.join(Estudiante, Estudiante.usuario_id == Usuario.id).where(Estudiante.programa_id == programa_id)
        elif rol == "COORDINADOR":
            ids = [
                c.usuario_id for c in db.scalars(select(CoordinadorPrograma))
                if programa_id in [int(x) for x in (c.programa_responsable_ids or [])]
            ]
            stmt = stmt.where(Usuario.id.in_(ids or [-1]))
    return list(db.scalars(stmt))
