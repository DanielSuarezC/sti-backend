"""Slice C2: la semilla extra deja a est5 con seguimiento C1 mixto, un ROJO con alerta y un F9 en borrador."""

from sqlalchemy import select

from app.models import EvaluacionPlan, Notificacion, RegistroSeguimientoAjuste, Seguimiento
from scripts.seed import run_seed
from scripts.seed_extra_c2 import seed


def test_seed_extra_c2(db):
    run_seed(db, demo=True)
    db.commit()
    out = seed(db)
    db.commit()
    assert out["seguimiento"] == "C1 (cerrado)" and len(out["rojos_sin_rediseno"]) == 1
    regs = list(db.scalars(select(RegistroSeguimientoAjuste)))
    assert sorted(str(r.semaforo) for r in regs) == ["AMARILLO", "ROJO", "VERDE"]
    assert db.query(Notificacion).filter_by(tipo="AJUSTE_SEMAFORO_ROJO").count() == 4  # alerta RF-39
    assert db.query(Notificacion).filter_by(tipo="TAREA_CONCERTACION").count() == 2
    assert db.query(EvaluacionPlan).one().estado == "BORRADOR"
    assert db.query(Seguimiento).one().cerrado is True
    assert seed(db)["omitido"]  # idempotente
