"""Entorno de Alembic: usa DATABASE_URL de la configuración y los modelos del STI.

    alembic upgrade head                      # aplica migraciones
    alembic revision --autogenerate -m "..."  # genera una nueva (revisar SIEMPRE el resultado)
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import JSON, engine_from_config, pool
from sqlalchemy.types import TypeDecorator

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401  (registra todas las tablas)
from app.core.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().effective_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Renderiza los TypeDecorator propios (cifrados / UTC) como tipos SQL genéricos y portables,
    y el JSON portable (JSONB solo como variante de PostgreSQL)."""
    if type_ == "type":
        if isinstance(obj, TypeDecorator):
            return _render_impl(obj.impl_instance if hasattr(obj, "impl_instance") else obj.impl)
        if isinstance(obj, JSON) and getattr(obj, "_variant_mapping", None):
            autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
            return "sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')"
    return False


def _render_impl(impl) -> str:
    from sqlalchemy import DateTime, Text

    if isinstance(impl, DateTime):
        return f"sa.DateTime(timezone={bool(impl.timezone)})"
    if isinstance(impl, Text):
        return "sa.Text()"
    return repr(impl)


def _is_sqlite() -> bool:
    import os

    if os.environ.get("ALEMBIC_NO_BATCH"):  # migración inicial: sin modo batch (DDL idéntico en SQLite y PostgreSQL)
        return False
    return config.get_main_option("sqlalchemy.url", "").startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        compare_type=True,
        render_as_batch=_is_sqlite(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            compare_type=True,
            render_as_batch=_is_sqlite(),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
