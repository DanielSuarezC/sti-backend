"""La migración inicial reproduce EXACTAMENTE los modelos y es válida para PostgreSQL."""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401
from alembic import command
from app.core import config
from app.models import Base

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


@pytest.fixture()
def migrated_url(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.reset_settings_cache()
    yield url
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    config.reset_settings_cache()


def test_alembic_upgrade_head_matches_models(migrated_url):
    command.upgrade(_cfg(), "head")
    eng = create_engine(migrated_url)
    tables = set(inspect(eng).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
    assert diff == [], diff
    command.downgrade(_cfg(), "base")
    assert set(inspect(create_engine(migrated_url)).get_table_names()) == {"alembic_version"}


def test_ddl_compiles_for_postgresql():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "sqlite" not in ddl.lower()
        for idx in table.indexes:
            str(CreateIndex(idx).compile(dialect=dialect))
    ddl = str(CreateTable(Base.metadata.tables["respuesta_aq10"]).compile(dialect=dialect))
    assert "TEXT" in ddl  # columnas cifradas = TEXT
    assert "JSONB" in str(CreateTable(Base.metadata.tables["estrategia_dua_catalogo"]).compile(dialect=dialect))
