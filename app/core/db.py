"""Motor y sesión de SQLAlchemy (SQLite en desarrollo/pruebas, PostgreSQL 16 en producción)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def build_engine(url: str | None = None, *, echo: bool | None = None) -> Engine:
    settings = get_settings()
    url = url or settings.effective_database_url
    echo = settings.db_echo if echo is None else echo
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, echo=echo, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, echo=echo, pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def configure_engine(url: str | None = None, engine: Engine | None = None) -> Engine:
    """Reconfigura el motor global (usado por pruebas y scripts)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = engine or build_engine(url)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def SessionLocal() -> Session:
    return get_session_factory()()


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión por petición. El router decide cuándo hacer `commit()`."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Contexto transaccional para scripts, tareas y workers."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db() -> bool:
    from sqlalchemy import text

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
