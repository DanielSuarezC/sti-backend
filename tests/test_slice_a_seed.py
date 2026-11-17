"""Slice A: la semilla adicional es idempotente y deja datos coherentes."""

from app.models import Asignatura, SolicitudIngreso
from app.services import params
from scripts.seed import run_seed
from scripts.seed_extra_a import seed


def test_seed_extra_a_idempotente(db):
    run_seed(db, demo=False)
    db.commit()
    primero = seed(db, demo=True)
    db.commit()
    assert primero["parametros"] >= 3 and primero["asignaturas"] == 3 and primero["solicitudes_demo"] == 1
    segundo = seed(db, demo=True)
    assert segundo["parametros"] == 0 and segundo["asignaturas"] == 0 and "solicitudes_demo" not in segundo
    assert db.query(SolicitudIngreso).count() == 1 and db.query(Asignatura).count() == 3
    assert params.get_param(db, "reportes_k_minimo") == 3
