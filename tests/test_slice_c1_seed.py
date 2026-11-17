"""Slice C1: la semilla extra deja planes demo coherentes (est5 aprobado e implementándose, est4 en negociación)."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AjusteRazonable, Estudiante, FirmaPlan, PlanMaarTea, TareaNegociacion, Usuario
from app.services import plan_builder
from app.services import plan_signatures as sig
from scripts import seed, seed_extra_c1


def test_seed_extra_c1(db):
    seed.run_seed(db, demo=True)
    db.commit()
    out = seed_extra_c1.seed(db)
    db.commit()
    assert "omitido" not in out, out
    e5 = db.scalar(select(Estudiante).join(Usuario, Usuario.id == Estudiante.usuario_id).where(Usuario.email.like("est5.%")))
    e4 = db.scalar(select(Estudiante).join(Usuario, Usuario.id == Estudiante.usuario_id).where(Usuario.email.like("est4.%")))
    p5 = db.scalar(select(PlanMaarTea).where(PlanMaarTea.estudiante_id == e5.id))
    assert p5.estado == "IMPLEMENTACION" and p5.version == 2
    ajustes = list(db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == p5.id)))
    assert {str(a.tipo_ajuste) for a in ajustes} == {"COMUNICACION", "PEDAGOGIA", "EVALUACION", "AMBIENTE", "INTERACCION", "TECNOLOGIA"}
    firmas = list(db.scalars(select(FirmaPlan).where(FirmaPlan.plan_id == p5.id)))
    assert sorted(f.version for f in firmas if f.estado == "FIRMADA") == [2, 2, 2]
    assert sorted(f.version for f in firmas if f.estado == "INVALIDADA") == [1, 1, 1]
    ver = sig.verificar(db, p5)
    assert ver["integro"] and ver["completo"]
    t = plan_builder.resumen_implementacion(db, p5.id)
    assert t["total_apoyos"] == 7 and t["implementados"] == 4
    p4 = db.scalar(select(PlanMaarTea).where(PlanMaarTea.estudiante_id == e4.id))
    assert p4.estado == "EN_NEGOCIACION"
    tarea = db.scalar(select(TareaNegociacion).where(TareaNegociacion.plan_id == p4.id))
    assert tarea.ciclo == 2 and tarea.estado == "ABIERTA" and len(tarea.historial) == 2
    # idempotente
    again = seed_extra_c1.seed(db)
    assert again["est4"] == "ya sembrado" and again["est5"] == "ya sembrado"
