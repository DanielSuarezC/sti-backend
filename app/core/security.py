"""Seguridad: hashing de contraseñas (argon2), JWT de acceso (8 h), refresh token con rotación en cookie
HttpOnly, bloqueo por intentos fallidos y tokens de activación (72 h) / recuperación."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.devsecrets import gen_jwt_secret, get_or_create_dev_secret
from app.core.errors import AppError, Locked, Unauthorized
from app.models.base import utcnow
from app.models.usuarios import RefreshToken, Usuario


def _make_hasher() -> PasswordHasher:
    if get_settings().is_test:  # parámetros mínimos SOLO en pruebas (acelera la suite)
        return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return PasswordHasher()  # argon2id con parámetros por defecto de argon2-cffi (RFC 9106, perfil bajo en memoria)


_ph = _make_hasher()


# --------------------------------------------------------------------------- contraseñas
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> None:
    """Política mínima: longitud configurable (10 por defecto), con letras y números."""
    min_len = get_settings().min_password_length
    problems = []
    if len(password) < min_len:
        problems.append(f"al menos {min_len} caracteres")
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", password):
        problems.append("al menos una letra")
    if not re.search(r"\d", password):
        problems.append("al menos un número")
    if problems:
        raise AppError(
            "La contraseña debe tener " + ", ".join(problems) + ".",
            "CONTRASENA_DEBIL",
            status_code=422,
        )


# --------------------------------------------------------------------------- tokens opacos
def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """(token_en_claro, hash_sha256). Solo el hash se persiste."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


# --------------------------------------------------------------------------- JWT de acceso
def _jwt_secret() -> str:
    s = get_settings().jwt_secret
    return s or get_or_create_dev_secret("JWT_SECRET", gen_jwt_secret)


def create_access_token(user: Usuario) -> tuple[str, int]:
    """Devuelve (jwt, expires_in_segundos). Claims: sub, rol, jti, iat, exp, typ=access."""
    settings = get_settings()
    now = utcnow()
    exp = now + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": str(user.id),
        "rol": str(user.rol),
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, settings.access_token_minutes * 60


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[get_settings().jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Su sesión expiró. Inicie sesión de nuevo.", "TOKEN_EXPIRADO")
    except jwt.PyJWTError:
        raise Unauthorized("Su sesión no es válida. Inicie sesión de nuevo.", "TOKEN_INVALIDO")
    if payload.get("typ") != "access":
        raise Unauthorized("Su sesión no es válida. Inicie sesión de nuevo.", "TOKEN_INVALIDO")
    return payload


# --------------------------------------------------------------------------- refresh token (rotación)
def issue_refresh_token(
    db: Session, user: Usuario, *, family_id: str | None = None, ip: str | None = None, user_agent: str | None = None
) -> tuple[str, RefreshToken]:
    settings = get_settings()
    raw, token_hash = new_opaque_token()
    rt = RefreshToken(
        usuario_id=user.id,
        token_hash=token_hash,
        family_id=family_id or uuid.uuid4().hex,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(rt)
    db.flush()
    return raw, rt


def revoke_family(db: Session, family_id: str) -> None:
    now = utcnow()
    for rt in db.scalars(select(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))):
        rt.revoked_at = now


def revoke_all_user_tokens(db: Session, usuario_id: int) -> None:
    now = utcnow()
    for rt in db.scalars(select(RefreshToken).where(RefreshToken.usuario_id == usuario_id, RefreshToken.revoked_at.is_(None))):
        rt.revoked_at = now


def rotate_refresh_token(
    db: Session, raw: str | None, *, ip: str | None = None, user_agent: str | None = None
) -> tuple[Usuario, str]:
    """Valida el refresh token, lo revoca y emite uno nuevo de la misma familia.

    Reutilizar un token ya rotado revoca TODA la familia (posible robo) y exige iniciar sesión de nuevo.
    """
    if not raw:
        raise Unauthorized("No hay una sesión activa. Inicie sesión.", "REFRESH_AUSENTE")
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if rt is None:
        raise Unauthorized("Su sesión no es válida. Inicie sesión de nuevo.", "REFRESH_INVALIDO")
    if rt.revoked_at is not None:
        revoke_family(db, rt.family_id)
        db.commit()
        raise Unauthorized("Detectamos un uso repetido de su sesión; por seguridad debe iniciar sesión de nuevo.",
                           "REFRESH_REUTILIZADO")
    if rt.expires_at <= utcnow():
        rt.revoked_at = utcnow()
        db.commit()
        raise Unauthorized("Su sesión expiró. Inicie sesión de nuevo.", "REFRESH_EXPIRADO")
    user = db.get(Usuario, rt.usuario_id)
    if user is None or str(user.estado) not in ("ACTIVO", "PENDIENTE_CONSENTIMIENTO"):
        rt.revoked_at = utcnow()
        db.commit()
        raise Unauthorized("Su cuenta no está activa.", "CUENTA_INACTIVA")
    new_raw, new_rt = issue_refresh_token(db, user, family_id=rt.family_id, ip=ip, user_agent=user_agent)
    rt.revoked_at = utcnow()
    rt.replaced_by_id = new_rt.id
    return user, new_raw


def set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.refresh_cookie_name,
        value=raw,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure or s.is_production,
        samesite=s.cookie_samesite,
        domain=s.cookie_domain or None,
        path=f"{s.api_prefix}/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        key=s.refresh_cookie_name, path=f"{s.api_prefix}/auth", domain=s.cookie_domain or None,
        secure=s.cookie_secure or s.is_production, httponly=True, samesite=s.cookie_samesite,
    )


# --------------------------------------------------------------------------- bloqueo por intentos fallidos
def assert_not_locked(user: Usuario) -> None:
    if user.locked_until is not None and user.locked_until > utcnow():
        minutos = max(1, int((user.locked_until - utcnow()).total_seconds() // 60) + 1)
        raise Locked(
            f"La cuenta está bloqueada por demasiados intentos fallidos. Intente de nuevo en {minutos} minuto(s) "
            "o use «Olvidé mi contraseña».",
            "CUENTA_BLOQUEADA",
            extra={"bloqueada_hasta": user.locked_until.isoformat()},
        )


def register_failed_login(user: Usuario) -> bool:
    """Suma un intento fallido; al llegar al máximo bloquea la cuenta. Devuelve True si quedó bloqueada."""
    s = get_settings()
    if user.locked_until is not None and user.locked_until <= utcnow():
        user.failed_attempts = 0  # el bloqueo anterior ya venció
        user.locked_until = None
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= s.max_login_attempts:
        user.locked_until = utcnow() + timedelta(minutes=s.lockout_minutes)
        return True
    return False


def reset_failed_logins(user: Usuario) -> None:
    user.failed_attempts = 0
    user.locked_until = None


# --------------------------------------------------------------------------- código de recuperación (sin correo)
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I para evitar errores al copiar


def normalize_recovery_code(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def new_recovery_code() -> tuple[str, str]:
    """(código legible `XXXX-XXXX-XXXX-XXXX`, hash). 16 caracteres de un alfabeto de 32 = 80 bits de entropía."""
    chars = "".join(secrets.choice(_ALFABETO) for _ in range(16))
    raw = "-".join(chars[i:i + 4] for i in range(0, 16, 4))
    return raw, hash_token(normalize_recovery_code(raw))


def issue_recovery_code(user: Usuario) -> str:
    """Genera un código nuevo (invalida el anterior) y devuelve el texto en claro. Hay que mostrarlo UNA vez."""
    raw, h = new_recovery_code()
    user.recovery_code_hash = h
    return raw


def verify_recovery_code(user: Usuario, raw: str) -> bool:
    if not user.recovery_code_hash:
        return False
    return secrets.compare_digest(user.recovery_code_hash, hash_token(normalize_recovery_code(raw)))


def new_temp_password() -> str:
    """Contraseña provisional que cumple la política (letras + números, >= min_password_length)."""
    n = max(get_settings().min_password_length, 12)
    body = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(n - 4))
    return f"{body}{secrets.randbelow(9000) + 1000}"


# --------------------------------------------------------------------------- activación / recuperación
def create_activation_token(user: Usuario, hours: int | None = None) -> str:
    """Genera token de activación (72 h por defecto) y guarda su hash en el usuario. Devuelve el token en claro."""
    hours = hours or get_settings().activation_token_hours
    raw, h = new_opaque_token()
    user.activation_token_hash = h
    user.activation_expires_at = utcnow() + timedelta(hours=hours)
    return raw


def create_reset_token(user: Usuario) -> str:
    raw, h = new_opaque_token()
    user.reset_token_hash = h
    user.reset_expires_at = utcnow() + timedelta(hours=get_settings().reset_token_hours)
    return raw


def find_user_by_activation_token(db: Session, raw: str) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.activation_token_hash == hash_token(raw)))
    if user is None:
        raise AppError("El enlace de activación no es válido. Pida una nueva invitación a su administrador.",
                       "TOKEN_ACTIVACION_INVALIDO", status_code=400)
    if user.activation_expires_at is None or user.activation_expires_at <= utcnow():
        raise AppError("El enlace de activación venció (dura 72 horas). Pida una nueva invitación.",
                       "TOKEN_ACTIVACION_VENCIDO", status_code=400)
    return user


def find_user_by_reset_token(db: Session, raw: str) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.reset_token_hash == hash_token(raw)))
    if user is None:
        raise AppError("El enlace para restablecer la contraseña no es válido. Solicite uno nuevo.",
                       "TOKEN_RECUPERACION_INVALIDO", status_code=400)
    if user.reset_expires_at is None or user.reset_expires_at <= utcnow():
        raise AppError("El enlace para restablecer la contraseña venció. Solicite uno nuevo.",
                       "TOKEN_RECUPERACION_VENCIDO", status_code=400)
    return user


def utc_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
