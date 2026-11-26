"""Alta de cuentas e invitaciones (compartido por Admin, Bienestar Vía 1, Vía 2, Vía 3 CSV, seed y scripts)."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, Unprocessable
from app.core.security import (
    create_activation_token,
    hash_password,
    issue_recovery_code,
    new_temp_password,
    reset_failed_logins,
    revoke_all_user_tokens,
    validate_password_strength,
)
from app.models.base import utcnow
from app.models.enums import EstadoUsuario, FuenteSSO, Rol, ViaIngreso
from app.models.usuarios import (
    CoordinadorPrograma,
    Docente,
    Estudiante,
    PersonalAdministrativo,
    PersonalBienestar,
    PreferenciaSensorialUI,
    Usuario,
)
from app.services.notifications import Evento, notify


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(
    db: Session,
    *,
    email: str,
    nombre_completo: str,
    rol: Rol | str,
    password: str | None = None,
    estado: EstadoUsuario | str | None = None,
    numero_documento: str | None = None,
    tipo_documento: str | None = None,
    telefono: str | None = None,
    perfil: dict[str, Any] | None = None,
    skip_password_policy: bool = False,
) -> Usuario:
    """Crea USUARIO + su perfil por rol (ESTUDIANTE/DOCENTE/COORDINADOR/BIENESTAR/ADMIN).

    * Sin `password` la cuenta queda sin contraseña (debe activarse con token de 72 h: `invite_user`).
    * `perfil` aporta campos del perfil de rol (p. ej. ESTUDIANTE: ``codigo_estudiante``, ``programa_id``,
      ``via_ingreso``; COORDINADOR: ``programa_responsable_ids``).
    * Hace flush, no commit.
    """
    rol = Rol(str(rol))
    email = normalize_email(email)
    if db.scalar(select(Usuario.id).where(Usuario.email == email)):
        raise Conflict("Ya existe una cuenta con ese correo electrónico.", "EMAIL_DUPLICADO")
    if estado is None:
        estado = EstadoUsuario.ACTIVO if password else EstadoUsuario.PENDIENTE_ACTIVACION
        if password and rol == Rol.ESTUDIANTE:
            estado = EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    user = Usuario(
        email=email, nombre_completo=nombre_completo.strip(), rol=rol, estado=EstadoUsuario(str(estado)),
        numero_documento=numero_documento, tipo_documento=tipo_documento, telefono=telefono,
        auth_source=FuenteSSO.LOCAL,
    )
    if password:
        if not skip_password_policy:
            validate_password_strength(password)
        user.password_hash = hash_password(password)
    db.add(user)
    db.flush()
    perfil = dict(perfil or {})
    if rol == Rol.ESTUDIANTE:
        if not perfil.get("codigo_estudiante"):
            raise Conflict("El código estudiantil es obligatorio para crear un estudiante.", "CODIGO_ESTUDIANTE_REQUERIDO")
        if db.scalar(select(Estudiante.id).where(Estudiante.codigo_estudiante == perfil["codigo_estudiante"])):
            raise Conflict("Ya existe un estudiante con ese código.", "CODIGO_ESTUDIANTE_DUPLICADO")
        perfil.setdefault("via_ingreso", ViaIngreso.BIENESTAR)
        db.add(Estudiante(usuario_id=user.id, **perfil))
    elif rol == Rol.DOCENTE:
        db.add(Docente(usuario_id=user.id, **perfil))
    elif rol == Rol.COORDINADOR:
        db.add(CoordinadorPrograma(usuario_id=user.id, **perfil))
    elif rol == Rol.BIENESTAR:
        db.add(PersonalBienestar(usuario_id=user.id, **perfil))
    elif rol == Rol.ADMIN:
        db.add(PersonalAdministrativo(usuario_id=user.id, **perfil))
    db.add(PreferenciaSensorialUI(usuario_id=user.id))
    db.flush()
    return user


def invite_user(db: Session, user: Usuario, *, actor: Usuario | None = None, request=None, extra: dict | None = None) -> str:
    """Genera el token de activación (72 h), envía la invitación por correo y devuelve el token en claro."""
    s = get_settings()
    raw = create_activation_token(user)
    enlace = f"{s.frontend_url.rstrip('/')}{s.activation_path}?token={raw}"
    payload = {
        "nombre": user.nombre_completo, "rol": str(user.rol), "enlace_activacion": enlace,
        "horas_validez": s.activation_token_hours,
    }
    payload.update(extra or {})
    notify(db, Evento.CUENTA_CREADA, [user], payload)
    audit.log(db, actor, audit.Accion.USUARIO_CREADO, "usuario", user.id, {"rol": str(user.rol), "invitacion": True},
              request=request)
    return raw


# ----------------------------------------------------------------------------- acceso sin correo
def activation_link(raw_token: str) -> str:
    s = get_settings()
    return f"{s.frontend_url.rstrip('/')}{s.activation_path}?token={raw_token}"


def _estado_tras_acceso(db: Session, user: Usuario) -> EstadoUsuario:
    from app.core.permissions import user_has_consent

    if str(user.rol) == Rol.ESTUDIANTE:
        return EstadoUsuario.ACTIVO if user_has_consent(db, user) else EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    return EstadoUsuario.ACTIVO


def provision_access(db: Session, user: Usuario, *, actor: Usuario | None = None, request=None,
                     extra: dict | None = None) -> dict[str, Any]:
    """Entrega el acceso a una cuenta creada por el personal (sin depender del correo).

    * Por defecto (`EMAIL_ACTIVATION_REQUIRED=false`): fija una **contraseña provisional**, deja la cuenta lista para
      entrar y devuelve las credenciales para que quien creó la cuenta se las entregue a la persona (se muestran una
      sola vez; la persona puede cambiarlas en «Mi cuenta»).
    * Con `EMAIL_ACTIVATION_REQUIRED=true`: genera el enlace de activación de 72 h (se envía por correo y también se
      devuelve para poder compartirlo por otro canal).
    No hace commit.
    """
    s = get_settings()
    if s.email_activation_required:
        raw = invite_user(db, user, actor=actor, request=request, extra=extra)
        return {"modo": "INVITACION", "email": user.email, "enlace_activacion": activation_link(raw),
                "horas_validez": s.activation_token_hours}
    temporal = new_temp_password()
    user.password_hash = hash_password(temporal)
    user.password_changed_at = utcnow()
    user.activation_token_hash = None
    user.activation_expires_at = None
    reset_failed_logins(user)
    user.estado = _estado_tras_acceso(db, user)
    revoke_all_user_tokens(db, user.id)
    codigo = issue_recovery_code(user) if not user.recovery_code_hash else None
    audit.log(db, actor, "ACCESO_PROVISIONADO", "usuario", user.id, {"rol": str(user.rol), "modo": "DIRECTO"},
              request=request)
    db.flush()
    return {"modo": "DIRECTO", "email": user.email, "password_temporal": temporal, "codigo_recuperacion": codigo}


ROLES_REGISTRO_LIBRE = (Rol.ESTUDIANTE, Rol.DOCENTE, Rol.FAMILIAR)
ROLES_REGISTRO_CON_CODIGO = (Rol.BIENESTAR, Rol.COORDINADOR)


def registro_roles_disponibles() -> list[str]:
    s = get_settings()
    roles = [str(r) for r in ROLES_REGISTRO_LIBRE]
    if s.staff_access_code:
        roles += [str(r) for r in ROLES_REGISTRO_CON_CODIGO]
    return roles


def register_self(db: Session, *, rol: Rol | str, email: str, nombre_completo: str, password: str,
                  telefono: str | None = None, codigo_estudiante: str | None = None, programa_id: int | None = None,
                  codigo_acceso: str | None = None, codigo_vinculacion: str | None = None,
                  request=None) -> tuple[Usuario, str]:
    """Registro autónomo: la cuenta queda lista al instante (sin verificar el correo). Devuelve (usuario, código de
    recuperación en claro). No hace commit."""
    from app.models.consentimiento import AutorizacionFamiliar  # evita import circular en el arranque
    from app.models.enums import EstadoAutorizacionFamiliar
    from app.services import student_intake

    s = get_settings()
    if not s.registro_abierto:
        raise Forbidden("El registro de cuentas está cerrado. Pida su cuenta a Bienestar Universitario.",
                        "REGISTRO_CERRADO")
    rol = Rol(str(rol))
    if rol in ROLES_REGISTRO_CON_CODIGO:
        if not s.staff_access_code:
            raise Forbidden("Este tipo de cuenta no se crea por registro libre. Pídala al administrador.",
                            "ROL_NO_DISPONIBLE_REGISTRO")
        if not codigo_acceso or not secrets.compare_digest(codigo_acceso.strip().encode(), s.staff_access_code.encode()):
            raise Forbidden("El código de acceso del personal no es correcto.", "CODIGO_PERSONAL_INCORRECTO")
    elif rol not in ROLES_REGISTRO_LIBRE:
        raise Forbidden("Este tipo de cuenta no se crea por registro libre. Pídala al administrador.",
                        "ROL_NO_DISPONIBLE_REGISTRO")

    email = normalize_email(email)
    if student_intake.email_taken(db, email):
        raise Conflict("Ya existe una cuenta con ese correo. Inicie sesión o recupere su contraseña con su código.",
                       "EMAIL_DUPLICADO")
    validate_password_strength(password)

    autorizaciones: list = []
    if rol == Rol.FAMILIAR:
        codigo = (codigo_vinculacion or "").strip().upper()
        if not codigo:
            raise Unprocessable("Escriba el código de vinculación que le dio el estudiante.",
                                "CODIGO_VINCULACION_REQUERIDO")
        autorizaciones = list(db.scalars(select(AutorizacionFamiliar).where(
            AutorizacionFamiliar.familiar_email == email, AutorizacionFamiliar.familiar_usuario_id.is_(None),
            AutorizacionFamiliar.codigo_vinculacion == codigo)))
        if not autorizaciones:
            raise Unprocessable("El código de vinculación no corresponde a este correo. Pida al estudiante que revise "
                                "el correo y el código en «Mi familia».", "CODIGO_VINCULACION_INVALIDO")

    if rol == Rol.ESTUDIANTE:
        codigo = (codigo_estudiante or "").strip()
        if not codigo:
            raise Unprocessable("Escriba su código estudiantil o número de documento.", "CODIGO_ESTUDIANTE_REQUERIDO")
        student_intake.get_programa_or_422(db, programa_id)
        user, _est = student_intake.create_student_account(
            db, nombre_completo=nombre_completo, email=email, codigo=codigo, programa_id=programa_id,
            via=ViaIngreso.AUTOIDENTIFICACION, estado=EstadoUsuario.PENDIENTE_CONSENTIMIENTO, telefono=telefono,
            crear_matricula=True)
    else:
        perfil: dict[str, Any] = {}
        if rol == Rol.DOCENTE and programa_id is not None:
            student_intake.get_programa_or_422(db, programa_id)
            perfil["programa_id"] = programa_id
        elif rol == Rol.COORDINADOR and programa_id is not None:
            student_intake.get_programa_or_422(db, programa_id)
            perfil["programa_responsable_ids"] = [programa_id]
        user = create_user(db, email=email, nombre_completo=nombre_completo, rol=rol, telefono=telefono,
                           perfil=perfil, estado=EstadoUsuario.ACTIVO)
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    for a in autorizaciones:
        a.familiar_usuario_id = user.id
        a.estado = EstadoAutorizacionFamiliar.VIGENTE
        a.codigo_vinculacion = None
    codigo_recuperacion = issue_recovery_code(user)
    audit.log(db, user, audit.Accion.USUARIO_CREADO, "usuario", user.id, {"rol": str(rol), "via": "REGISTRO_AUTONOMO"},
              request=request)
    db.flush()
    return user, codigo_recuperacion
