"""Alta de cuentas e invitaciones (compartido por Admin, Bienestar Vía 1, Vía 2, Vía 3 CSV, seed y scripts)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.errors import Conflict
from app.core.security import create_activation_token, hash_password, validate_password_strength
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
