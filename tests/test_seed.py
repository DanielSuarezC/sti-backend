from sqlalchemy import func, select

from app.models import (
    CuestionarioAQ10,
    EstadoPlan,
    EstrategiaDuaCatalogo,
    PlanMaarTea,
    RespuestaAQ10,
    Usuario,
)
from app.models.enums import Escenario, TipoBarrera
from scripts.create_admin import create_admin
from scripts.seed import run_seed


def test_seed_reference_and_idempotent(db):
    r1 = run_seed(db, demo=False)
    db.commit()
    assert r1["referencia"]["catalogo_dua"] >= 30
    r2 = run_seed(db, demo=False)
    db.commit()
    assert r2["referencia"]["catalogo_dua"] == 0 and r2["referencia"]["estados_plan"] == 0
    cat = db.scalars(select(EstrategiaDuaCatalogo)).all()
    assert len(cat) >= 30
    assert {e for c in cat for e in c.escenarios} == {e.value for e in Escenario}  # los 8 escenarios
    assert {t for c in cat for t in c.tipos_barrera} == {t.value for t in TipoBarrera}  # los 8 tipos
    assert {c.pauta for c in cat} == set(range(1, 10))  # 9 pautas
    assert {c.principio for c in cat} == {"REPRESENTACION", "ACCION_EXPRESION", "PARTICIPACION"}
    assert len({c.codigo for c in cat}) == len(cat)
    aq = db.scalar(select(CuestionarioAQ10))
    assert len(aq.items) == 10 and aq.punto_corte == 6 and len(aq.opciones) == 4
    agree = {i["numero"] for i in aq.items if i["puntua_si"] == "ACUERDO"}
    assert agree == {1, 7, 8, 10}
    assert db.scalar(select(func.count()).select_from(EstadoPlan)) == 11


def test_seed_demo(db):
    out = run_seed(db, demo=True)
    db.commit()
    assert len(out["demo"]["usuarios"]) == 9  # 4 roles + 5 estudiantes
    assert db.scalar(select(func.count()).select_from(PlanMaarTea)) == 1
    assert db.scalar(select(func.count()).select_from(RespuestaAQ10)) == 2
    est4 = db.scalar(select(RespuestaAQ10))
    assert est4.puntaje == 7 and est4.supera_umbral
    assert db.scalar(select(Usuario).where(Usuario.email == "bienestar.demo@sti-demo.example.com"))
    run_seed(db, demo=True)  # idempotente
    db.commit()
    assert db.scalar(select(func.count()).select_from(PlanMaarTea)) == 1


def test_demo_login_works(client, db):
    run_seed(db, demo=True)
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "bienestar.demo@sti-demo.example.com", "password": "Demo-STI-2026!"})
    assert r.status_code == 200 and r.json()["user"]["rol"] == "BIENESTAR"
    r = client.post("/api/v1/auth/login", json={"email": "est2.demo@sti-demo.example.com", "password": "Demo-STI-2026!"})
    assert r.json()["user"]["estado"] == "PENDIENTE_CONSENTIMIENTO" and r.json()["user"]["consentimiento_firmado"] is False


def test_create_admin(db):
    u, creado = create_admin(db, "Admin@Example.com", "AdminClave2026")
    db.commit()
    assert creado and u.email == "admin@example.com" and u.rol == "ADMIN"
    u2, creado2 = create_admin(db, "admin@example.com", "OtraClave20267")
    assert not creado2 and u2.id == u.id
