"""Cifrado en reposo AES-256-GCM y TypeDecorators para SQLAlchemy.

Formato almacenado: ``v1:`` + base64url(nonce[12] || ciphertext || tag[16]).
La clave (`DATA_ENCRYPTION_KEY`) es base64 de 32 bytes. En desarrollo se genera una clave
local si falta (ver `devsecrets`); en producción su ausencia es un error de arranque.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import date
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings
from app.core.devsecrets import ConfigError, gen_aes_key, get_or_create_dev_secret

PREFIX = "v1:"


class DecryptionError(RuntimeError):
    """No fue posible descifrar un valor (clave incorrecta o dato alterado)."""


@lru_cache
def _aesgcm() -> AESGCM:
    key_b64 = get_settings().data_encryption_key
    if not key_b64:
        key_b64 = get_or_create_dev_secret("DATA_ENCRYPTION_KEY", gen_aes_key)
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConfigError("DATA_ENCRYPTION_KEY no es base64 válido. Genere una con: python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\"") from exc
    if len(key) != 32:
        raise ConfigError("DATA_ENCRYPTION_KEY debe decodificar exactamente a 32 bytes (AES-256).")
    return AESGCM(key)


def reset_crypto_cache() -> None:
    _aesgcm.cache_clear()


def validate_key() -> None:
    """Falla temprano (arranque) si la clave falta en producción o es inválida."""
    _aesgcm()


def encrypt_str(plain: str, aad: bytes | None = None) -> str:
    nonce = os.urandom(12)
    ct = _aesgcm().encrypt(nonce, plain.encode("utf-8"), aad)
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_str(token: str, aad: bytes | None = None) -> str:
    if not token.startswith(PREFIX):
        raise DecryptionError("El valor almacenado no tiene formato cifrado válido.")
    try:
        raw = base64.urlsafe_b64decode(token[len(PREFIX):].encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        return _aesgcm().decrypt(nonce, ct, aad).decode("utf-8")
    except Exception as exc:  # InvalidTag, binascii.Error, etc.
        raise DecryptionError("No se pudo descifrar el dato (clave incorrecta o dato alterado).") from exc


class EncryptedText(TypeDecorator):
    """Texto cifrado con AES-256-GCM (columna TEXT)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_str(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_str(value)


class EncryptedJSON(TypeDecorator):
    """Estructura JSON (dict/list/escalar) serializada y cifrada."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_str(json.dumps(value, ensure_ascii=False, default=str))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(decrypt_str(value))


class EncryptedDate(TypeDecorator):
    """Fecha (`datetime.date`) cifrada como texto ISO-8601."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = date.fromisoformat(value)
        return encrypt_str(value.isoformat())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return date.fromisoformat(decrypt_str(value))
