"""Salud del servicio: `GET /api/v1/health` (y `GET /health` en la raíz, ver main.py)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import check_db

router = APIRouter(tags=["health"])


def health_payload() -> tuple[dict, int]:
    s = get_settings()
    db_ok = check_db()
    body = {
        "status": "ok" if db_ok else "degradado",
        "version": s.app_version,
        "entorno": s.app_env,
        "base_de_datos": "ok" if db_ok else "sin_conexion",
        "tareas": "celery" if s.celery_broker_url else "en_linea",
        "correo": "smtp" if s.smtp_configured else "outbox",
        "almacenamiento": "r2" if s.r2_configured else "disco_local",
    }
    return body, 200 if db_ok else 503


@router.get("/health")
def health():
    body, code = health_payload()
    return JSONResponse(body, status_code=code)
