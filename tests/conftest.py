"""Fixtures: app + BD SQLite en memoria por prueba + fábricas por rol."""

from __future__ import annotations

import os

# Entorno de pruebas ANTES de importar la app (la configuración se cachea).
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite://",
        "LOGIN_RATE_LIMIT_PER_MINUTE": "0",
        "SMTP_HOST": "",
        "CELERY_BROKER_URL": "",
        "R2_ENDPOINT_URL": "",
        "SENTRY_DSN": "",
        "JWT_SECRET": "",
        "DATA_ENCRYPTION_KEY": "",
        "STORAGE_DIR": os.path.join(os.path.dirname(__file__), ".storage_tmp"),
        "BIENESTAR_SCOPE": "all",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import reset_settings_cache  # noqa: E402
from app.core.db import build_engine, configure_engine, get_db  # noqa: E402
from app.core.ratelimit import reset_rate_limits  # noqa: E402

reset_settings_cache()

import app.models  # noqa: E402, F401
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from tests import factories  # noqa: E402


@pytest.fixture()
def engine():
    eng = build_engine("sqlite://")
    Base.metadata.create_all(eng)
    configure_engine(engine=eng)
    reset_rate_limits()
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = create_app()

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    from tests._probe_router import router as probe_router

    app.include_router(probe_router)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def world(db):
    """Programa + usuarios de todos los roles (con consentimiento del estudiante)."""
    return factories.build_world(db)


@pytest.fixture()
def auth():
    return factories.auth_headers
