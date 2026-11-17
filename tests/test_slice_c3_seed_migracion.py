"""Semilla extra C3 (idempotente) y migracion 00C3 (tabla f10_semestre)."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select

from alembic import command
from app.core import config
from app.models import AutorizacionFamiliar, Base, Estudiante, HitoTrayectoria, NotaContinuidad, TrayectoriaAcademica
from scripts import seed as seed_mod
from scripts import seed_extra_c3

ROOT = Path(__file__).resolve().parents[1]


def test_seed_extra_c3_idempotente(db):
    assert "omitido" in seed_extra_c3.seed(db)  # sin demo no hace nada
    seed_mod.run_seed(db, demo=True)
    db.commit()
    r1 = seed_extra_c3.seed(db)
    db.commit()
    assert r1["nota_pendiente"] and r1["f10"] and r1["hitos"] == 2
    assert seed_extra_c3.seed(db) == {}  # segunda corrida: nada nuevo
    db.commit()
    est = db.scalar(select(Estudiante).where(Estudiante.codigo_estudiante == "DEMO0005"))
    assert len(db.scalars(select(TrayectoriaAcademica).where(TrayectoriaAcademica.estudiante_id == est.id)).all()) == 2
    assert len(db.scalars(select(HitoTrayectoria)).all()) == 2
    nota = db.scalars(select(NotaContinuidad)).one()
    assert str(nota.estado) == "PENDIENTE_APROBACION_ESTUDIANTE"
    assert len(db.scalars(select(AutorizacionFamiliar).where(AutorizacionFamiliar.estudiante_id == est.id)).all()) == 2


def test_migracion_00c3_crea_f10_semestre_igual_al_modelo(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'c3.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.reset_settings_cache()
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(cfg, "00C3")  # 0001 -> 00C3 (sin depender de los demas slices)
        eng = create_engine(url)
        assert "f10_semestre" in inspect(eng).get_table_names()
        with eng.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
        assert [d for d in diff if "f10_semestre" in repr(d)] == []
        command.downgrade(cfg, "0001")
        assert "f10_semestre" not in inspect(create_engine(url)).get_table_names()
    finally:
        monkeypatch.setenv("DATABASE_URL", "sqlite://")
        config.reset_settings_cache()
