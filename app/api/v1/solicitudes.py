"""Solicitudes de ingreso Vía 2 (RF-04): formulario público + revisión por Bienestar.

# OWNER: slice A. El solicitante NUNCA entra sin aprobación humana; la respuesta pública no revela si el código existe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import get_db, require_roles
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.ratelimit import check_rate_limit
from app.models.academico import ProgramaAcademico
from app.models.base import utcnow
from app.models.consentimiento import SolicitudIngreso
from app.models.enums import EstadoSolicitudIngreso, EstadoUsuario, Rol, ViaIngreso
from app.models.usuarios import Usuario
from app.schemas.solicitudes import AprobarBody, RechazarBody, SolicitudPublica
from app.services import student_intake
from app.services.accounts import invite_user, normalize_email
from app.services.directorio import directory_settings, get_directorio, mensaje_dominio
from app.services.messaging import queue_email
from app.services.notifications import Evento, notify

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

BIENESTAR_ADMIN = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))
RESPUESTA_PUBLICA = (
    "Recibimos su solicitud. Un profesional de Bienestar la revisará y le escribirá al correo institucional que indicó. "
    "Hasta entonces no podrá ingresar al sistema."
)


def _out(db: Session, s: SolicitudIngreso) -> dict:
    prog = db.get(ProgramaAcademico, s.programa_id) if s.programa_id else None
    return {
        "id": s.id, "codigo_estudiantil": s.codigo_estudiantil, "email_institucional": s.email_institucional,
        "nombre_completo": s.nombre_completo, "telefono": s.telefono, "programa_id": s.programa_id,
        "programa_nombre": prog.nombre_programa if prog else None, "estado": str(s.estado),
        "verificada_directorio": s.verificada_directorio, "created_at": s.created_at, "revisado_por_id": s.revisado_por_id,
        "revisado_at": s.revisado_at, "motivo_rechazo": s.motivo_rechazo, "usuario_creado_id": s.usuario_creado_id,
    }


@router.get("/programas")
def programas_publicos(db: Session = Depends(get_db)):
    """Lista pública (id, nombre) de programas para el formulario de solicitud."""
    rows = db.scalars(select(ProgramaAcademico).order_by(ProgramaAcademico.nombre_programa)).all()
    return {"items": [{"id": p.id, "nombre": p.nombre_programa} for p in rows]}


@router.post("/publica", status_code=202)
def solicitud_publica(body: SolicitudPublica, request: Request, db: Session = Depends(get_db)):
    """Formulario público (sin autenticación). Con límite por IP y honeypot. La respuesta es siempre la misma."""
    ip = audit.client_ip(request) or "desconocida"
    check_rate_limit(f"solicitud:{ip}", directory_settings().solicitudes_rate_limit_per_hour, 3600)
    if body.sitio_web:  # honeypot: un bot rellenó el campo oculto; se ignora en silencio
        audit.log(db, None, "SOLICITUD_INGRESO_HONEYPOT", "solicitud_ingreso", None, request=request, actor_rol="PUBLICO", commit=True)
        return {"detail": RESPUESTA_PUBLICA}
    if not body.acepta_aviso_privacidad:
        raise Unprocessable("Debe aceptar el aviso de privacidad para enviar la solicitud.", "AVISO_PRIVACIDAD_REQUERIDO")
    email = normalize_email(body.email_institucional)
    codigo = body.codigo_estudiantil.strip()
    res = get_directorio().verificar(db, codigo, email)
    if not res.dominio_ok:
        raise Unprocessable(f"El correo no es institucional. {mensaje_dominio()}", "CORREO_NO_INSTITUCIONAL")
    if body.programa_id is not None and db.get(ProgramaAcademico, body.programa_id) is None:
        raise Unprocessable("El programa indicado no existe. Elija uno de la lista.", "PROGRAMA_INVALIDO")
    ya_cuenta = student_intake.codigo_taken(db, codigo) or student_intake.email_taken(db, email)
    ya_pendiente = db.scalar(select(SolicitudIngreso.id).where(
        SolicitudIngreso.estado == EstadoSolicitudIngreso.PENDIENTE,
        or_(SolicitudIngreso.codigo_estudiantil == codigo, SolicitudIngreso.email_institucional == email)).limit(1))
    if ya_cuenta or ya_pendiente:  # sin crear nada y sin revelar nada
        audit.log(db, None, "SOLICITUD_INGRESO_DUPLICADA", "solicitud_ingreso", None, request=request, actor_rol="PUBLICO", commit=True)
        return {"detail": RESPUESTA_PUBLICA}
    sol = SolicitudIngreso(
        codigo_estudiantil=codigo, email_institucional=email, nombre_completo=body.nombre_completo.strip(),
        telefono=body.telefono, programa_id=body.programa_id or res.programa_id, estado=EstadoSolicitudIngreso.PENDIENTE,
        verificada_directorio=res.valido is True, acepta_aviso_privacidad=True, ip=ip[:50],
    )
    db.add(sol)
    db.flush()
    bienestar = list(db.scalars(select(Usuario.id).where(Usuario.rol == Rol.BIENESTAR, Usuario.estado == EstadoUsuario.ACTIVO)))
    notify(db, Evento.SOLICITUD_INGRESO_NUEVA, bienestar, {"enlace": "/bienestar/solicitudes"})
    audit.log(db, None, "SOLICITUD_INGRESO_CREADA", "solicitud_ingreso", sol.id, {"verificada_directorio": sol.verificada_directorio},
              request=request, actor_rol="PUBLICO")
    db.commit()
    return {"detail": RESPUESTA_PUBLICA}


@router.get("")
def listar_solicitudes(estado: EstadoSolicitudIngreso | None = None, q: str | None = None, params: PageParams = Depends(),
                       db: Session = Depends(get_db), _=BIENESTAR_ADMIN):
    stmt = select(SolicitudIngreso).order_by(SolicitudIngreso.created_at.desc())
    if estado:
        stmt = stmt.where(SolicitudIngreso.estado == estado)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(SolicitudIngreso.nombre_completo).like(like),
                              func.lower(SolicitudIngreso.email_institucional).like(like),
                              SolicitudIngreso.codigo_estudiantil.like(f"%{q.strip()}%")))
    return paginate(db, stmt, params, lambda s: _out(db, s))


def _pendiente(db: Session, sid: int) -> SolicitudIngreso:
    s = db.get(SolicitudIngreso, sid)
    if s is None:
        raise NotFound("No encontramos esa solicitud.", "SOLICITUD_NO_ENCONTRADA")
    if s.estado != EstadoSolicitudIngreso.PENDIENTE:
        raise Conflict("Esta solicitud ya fue resuelta.", "SOLICITUD_YA_RESUELTA")
    return s


@router.post("/{solicitud_id}/aprobar")
def aprobar(solicitud_id: int, request: Request, body: AprobarBody | None = None, db: Session = Depends(get_db),
            actor: Usuario = BIENESTAR_ADMIN):
    s = _pendiente(db, solicitud_id)
    programa_id = (body.programa_id if body and body.programa_id else None) or s.programa_id
    student_intake.get_programa_or_422(db, programa_id)
    student_intake.validar_email_institucional(s.email_institucional)
    user, est = student_intake.create_student_account(
        db, nombre_completo=s.nombre_completo, email=s.email_institucional, codigo=s.codigo_estudiantil,
        programa_id=programa_id, via=ViaIngreso.AUTOIDENTIFICACION, estado=EstadoUsuario.PENDIENTE_ACTIVACION,
        telefono=s.telefono, bienestar_asignado_id=actor.id if str(actor.rol) == Rol.BIENESTAR else None,
    )
    invite_user(db, user, actor=actor, request=request)
    s.estado = EstadoSolicitudIngreso.APROBADA
    s.programa_id = programa_id
    s.revisado_por_id, s.revisado_at, s.usuario_creado_id = actor.id, utcnow(), user.id
    audit.log(db, actor, "SOLICITUD_INGRESO_APROBADA", "solicitud_ingreso", s.id, {"estudiante_id": est.id}, request=request,
              estudiante_id=est.id)
    db.commit()
    return {**_out(db, s), "detail": "Solicitud aprobada. Enviamos la invitación de activación (72 horas) al correo institucional."}


@router.post("/{solicitud_id}/rechazar")
def rechazar(solicitud_id: int, body: RechazarBody, request: Request, db: Session = Depends(get_db),
             actor: Usuario = BIENESTAR_ADMIN):
    s = _pendiente(db, solicitud_id)
    s.estado = EstadoSolicitudIngreso.RECHAZADA
    s.revisado_por_id, s.revisado_at, s.motivo_rechazo = actor.id, utcnow(), body.motivo.strip()
    queue_email(
        db, to_email=s.email_institucional, asunto="Respuesta a su solicitud de ingreso al STI", evento="SOLICITUD_INGRESO_RESUELTA",
        cuerpo=(f"Hola {s.nombre_completo}.\n\nRevisamos su solicitud de ingreso al Sistema Tutor Inteligente y por ahora no pudimos "
                "aprobarla. Si cree que es un error o quiere hablar del proceso, escriba a Bienestar Universitario.\n\n"
                "Sistema Tutor Inteligente (STI) - Universidad de Córdoba."),
        dedupe_key=f"solicitud_rechazada:{s.id}",
    )
    audit.log(db, actor, "SOLICITUD_INGRESO_RECHAZADA", "solicitud_ingreso", s.id, request=request)
    db.commit()
    return _out(db, s)
