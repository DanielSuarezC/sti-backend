"""Alta de estudiantes por las tres vías (RF-04): lógica compartida por Vía 1 (Bienestar), Vía 2 (solicitud
aprobada) y Vía 3 (CSV de admisiones).

Reglas: el estudiante NUNCA entra sin F0; las cuentas nacen sin contraseña y se activan con un token de 72 h.
Vía 1 y Vía 2 -> PENDIENTE_ACTIVACION (al activar pasan a PENDIENTE_CONSENTIMIENTO, `/auth/activate`).
Vía 3 -> PENDIENTE_CONSENTIMIENTO desde el inicio (correo explicativo con enlace al F0); sin F0 a los 30 días
se purga la cuenta (`jobs.purge_unconsented_accounts`).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.errors import Conflict, Unprocessable
from app.core.security import create_activation_token
from app.models.academico import CalendarioAcademico, Matricula, ProgramaAcademico
from app.models.enums import EstadoUsuario, Rol, ViaIngreso
from app.models.usuarios import Estudiante, Usuario
from app.services.accounts import create_user, invite_user, normalize_email
from app.services.directorio import email_dominio_permitido, mensaje_dominio
from app.services.messaging import queue_email

_PIE = "\n\nSistema Tutor Inteligente (STI) - Universidad de Córdoba.\nSi tiene dudas, responda a Bienestar Universitario."


def email_taken(db: Session, email: str) -> bool:
    return db.scalar(
        select(Usuario.id).where(Usuario.email == normalize_email(email)).execution_options(include_deleted=True)
    ) is not None


def codigo_taken(db: Session, codigo: str) -> bool:
    return db.scalar(
        select(Estudiante.id).where(Estudiante.codigo_estudiante == codigo).execution_options(include_deleted=True)
    ) is not None


def validar_email_institucional(email: str) -> None:
    if not email_dominio_permitido(email):
        raise Unprocessable(f"El correo no es institucional. {mensaje_dominio()}", "CORREO_NO_INSTITUCIONAL")


def get_programa_or_422(db: Session, programa_id: int | None) -> ProgramaAcademico:
    prog = db.get(ProgramaAcademico, programa_id) if programa_id else None
    if prog is None:
        raise Unprocessable("El programa académico indicado no existe. Elija uno de la lista.", "PROGRAMA_INVALIDO")
    return prog


def semestre_activo(db: Session, programa_id: int | None = None) -> CalendarioAcademico | None:
    """Calendario activo del programa (si tiene uno propio) o el institucional."""
    stmt = select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True))
    rows = db.scalars(stmt.order_by(CalendarioAcademico.id.desc())).all()
    if programa_id is not None:
        for r in rows:
            if r.programa_id == programa_id:
                return r
    for r in rows:
        if r.programa_id is None:
            return r
    return None


def create_student_account(
    db: Session, *, nombre_completo: str, email: str, codigo: str, programa_id: int, via: ViaIngreso,
    estado: EstadoUsuario, telefono: str | None = None, bienestar_asignado_id: int | None = None,
    anio_ingreso: int | None = None, semestre_actual: int | None = None, crear_matricula: bool = False,
    hoy: date | None = None,
) -> tuple[Usuario, Estudiante]:
    """Crea USUARIO + ESTUDIANTE (sin contraseña). Valida duplicados (incluye cuentas archivadas). Sin commit."""
    email = normalize_email(email)
    if email_taken(db, email):
        raise Conflict("Ya existe una cuenta con ese correo electrónico.", "EMAIL_DUPLICADO")
    if codigo_taken(db, codigo):
        raise Conflict("Ya existe un estudiante con ese código estudiantil.", "CODIGO_ESTUDIANTE_DUPLICADO")
    perfil: dict = {"codigo_estudiante": codigo, "programa_id": programa_id, "via_ingreso": via}
    if bienestar_asignado_id:
        perfil["bienestar_asignado_id"] = bienestar_asignado_id
    if anio_ingreso:
        perfil["anio_ingreso"] = anio_ingreso
    if semestre_actual:
        perfil["semestre_actual"] = semestre_actual
    user = create_user(db, email=email, nombre_completo=nombre_completo, rol=Rol.ESTUDIANTE, estado=estado,
                       telefono=telefono, perfil=perfil)
    est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == user.id))
    if crear_matricula:
        cal = semestre_activo(db, programa_id)
        if cal is not None:
            db.add(Matricula(estudiante_id=est.id, programa_academico_id=programa_id,
                             semestre_academico=cal.semestre_academico, fecha_matricula=hoy or date.today()))
            db.flush()
    return user, est


def send_via3_email(db: Session, user: Usuario, *, actor: Usuario | None = None) -> None:
    """Vía 3: correo explicativo del STI con enlace de activación (72 h) y camino al F0."""
    s = get_settings()
    raw = create_activation_token(user)
    base = s.frontend_url.rstrip("/")
    enlace = f"{base}{s.activation_path}?token={raw}"
    cuerpo = (
        f"Hola {user.nombre_completo}.\n\n"
        "La Universidad de Córdoba cuenta con el Sistema Tutor Inteligente (STI), una herramienta de Bienestar "
        "Universitario para acompañar a los estudiantes y ofrecer apoyos y ajustes razonables cuando los necesiten. "
        "Su programa nos compartió sus datos básicos (nombre, código y correo institucional) para crearle una cuenta.\n\n"
        "Su participación es voluntaria. Antes de usar el sistema debe leer y firmar el consentimiento informado (F0): "
        "allí le explicamos qué datos se recogen, quién puede verlos y cómo los protegemos. "
        "Puede retirar su consentimiento cuando quiera, sin consecuencias académicas. Si no firma, "
        "sus datos básicos se eliminan a los 30 días.\n\n"
        f"1) Active su cuenta y elija su contraseña (el enlace dura {s.activation_token_hours} horas):\n{enlace}\n"
        f"2) Luego ingrese y firme el consentimiento (F0): {base}/estudiante/consentimiento"
        + _PIE
    )
    queue_email(db, to_email=user.email, asunto="Bienvenido al STI: lea y firme su consentimiento informado (F0)",
                cuerpo=cuerpo, evento="CUENTA_CREADA_CSV", usuario_id=user.id)
    audit.log(db, actor, audit.Accion.USUARIO_CREADO, "usuario", user.id,
              {"rol": "ESTUDIANTE", "via": "MATRICULA_CSV", "invitacion": True})


def resend_invitation(db: Session, user: Usuario, *, actor: Usuario, request=None) -> None:
    """Reenvía la invitación (nuevo token de 72 h). Solo cuentas sin contraseña y pendientes."""
    if user.password_hash or str(user.estado) not in (
        EstadoUsuario.PENDIENTE_ACTIVACION, EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    ):
        raise Conflict("Esta cuenta ya fue activada: no necesita invitación. Si olvidó la contraseña, use "
                       "«Recuperar contraseña».", "CUENTA_YA_ACTIVADA")
    via3 = str(user.rol) == Rol.ESTUDIANTE and str(user.estado) == EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    if via3:
        send_via3_email(db, user, actor=actor)
    else:
        invite_user(db, user, actor=actor, request=request)
    audit.log(db, actor, "INVITACION_REENVIADA", "usuario", user.id, {"rol": str(user.rol)}, request=request)
