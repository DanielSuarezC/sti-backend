"""Secretos de desarrollo: se generan una vez y se guardan en `.dev_secrets.json` (ignorado por git).

En producción NUNCA se generan: si faltan, se lanza `ConfigError` con instrucciones claras.
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from app.core.config import BASE_DIR, get_settings

_FILE = Path(BASE_DIR) / ".dev_secrets.json"


class ConfigError(RuntimeError):
    """Configuración inválida o incompleta (mensaje en español, accionable)."""


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover - disco de solo lectura
        pass


def get_or_create_dev_secret(name: str, generator) -> str:
    settings = get_settings()
    if settings.is_production:
        raise ConfigError(
            f"Falta la variable de entorno requerida en producción ({name}). "
            "Genere un valor seguro y configúrelo en el entorno de despliegue."
        )
    if settings.is_test:
        # Determinista en pruebas: nunca escribe en disco.
        return generator(deterministic=True)
    data = _load()
    if name not in data:
        data[name] = generator(deterministic=False)
        _save(data)
    return data[name]


def gen_aes_key(deterministic: bool = False) -> str:
    raw = b"sti-test-key-0123456789abcdef-32" if deterministic else secrets.token_bytes(32)
    raw = (raw + b"\0" * 32)[:32]
    return base64.b64encode(raw).decode()


def gen_jwt_secret(deterministic: bool = False) -> str:
    return "sti-test-jwt-secret-not-for-production-use-0123456789" if deterministic else secrets.token_urlsafe(64)
