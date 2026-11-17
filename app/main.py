"""Aplicación FastAPI del STI.

Arranque local:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import app.models  # noqa: F401  (registra todas las tablas)
from app.api.v1.health import health_payload
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.crypto import validate_key
from app.core.errors import register_error_handlers
from app.core.middleware import install_middleware

logger = logging.getLogger("sti")


def _init_sentry() -> None:
    dsn = get_settings().sentry_dsn
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, environment=get_settings().app_env, traces_sample_rate=0.05, send_default_pii=False)
        logger.info("Sentry activado")
    except Exception:  # pragma: no cover
        logger.exception("No se pudo iniciar Sentry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=logging.DEBUG if s.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    validate_key()  # falla temprano si falta la clave de cifrado en producción
    from app.core.security import _jwt_secret

    _jwt_secret()  # idem para JWT_SECRET
    if s.is_production and not s.jobs_secret:
        logger.warning("JOBS_SECRET no está configurado: el endpoint de jobs diarios estará deshabilitado.")
    _init_sentry()
    logger.info("STI listo (entorno=%s, BD=%s)", s.app_env, "sqlite" if s.is_sqlite else "postgresql")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version=s.app_version,
        description="API del Sistema Tutor Inteligente (Plan MAAR-TEA) - errores en formato {detail, code}.",
        lifespan=lifespan,
        docs_url=None if s.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if s.is_production else "/openapi.json",
    )
    install_middleware(app)
    register_error_handlers(app)
    app.include_router(api_router, prefix=s.api_prefix)

    @app.get("/health", tags=["health"])
    def health_root():
        body, code = health_payload()
        return JSONResponse(body, status_code=code)

    return app


app = create_app()
