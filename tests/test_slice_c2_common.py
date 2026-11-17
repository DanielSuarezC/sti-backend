"""Utilidades compartidas por las pruebas del slice C2 (sin pruebas propias)."""

from __future__ import annotations

from datetime import date, timedelta

from app.models import (
    AjusteRazonable,
    BarreraIdentificada,
    CalendarioAcademico,
    EstadoPlan,
    EstrategiaDua,
    EstrategiaDuaCatalogo,
)
from app.models.enums import EstadoPlanEnum, TipoAjuste, TipoBarrera
from tests.factories import auth_headers, make_plan_with_ajuste


def hoy() -> date:
    return date.today()


def make_calendario(db, *, activo: bool = True) -> CalendarioAcademico:
    h = hoy()
    cal = CalendarioAcademico(
        semestre_academico="2026-II", programa_id=None, fecha_inicio=h - timedelta(days=70), fecha_fin=h + timedelta(days=60),
        fecha_c1=h - timedelta(days=14), fecha_c2=h + timedelta(days=7), fecha_c3=h + timedelta(days=30), activo=activo,
    )
    db.add(cal)
    db.commit()
    return cal


def make_plan_impl(db, w, *, n_ajustes: int = 2, estado: EstadoPlanEnum = EstadoPlanEnum.IMPLEMENTACION):
    """Plan en IMPLEMENTACION con `n_ajustes` ajustes; el docente de `w` es responsable del primero (asignatura ENF101)."""
    plan, a1 = make_plan_with_ajuste(db, w.estudiante, w.bienestar, asignatura=w.asignatura, estado=estado)
    a1.responsable_id = w.docente.id
    ajustes = [a1]
    for i in range(2, n_ajustes + 1):
        b = BarreraIdentificada(estudiante_id=w.estudiante.id, tipo_barrera=TipoBarrera.COMUNICATIVA,
                                descripcion_barrera=f"Barrera {i}", fecha_identificacion=hoy())
        db.add(b)
        db.flush()
        a = AjusteRazonable(plan_id=plan.id, barrera_asociada_id=b.id, nombre_ajuste=f"Ajuste {i}",
                            descripcion_ajuste="Instrucciones escritas", justificacion="Reduce ambigüedad",
                            tipo_ajuste=TipoAjuste.COMUNICACION, fecha_inicio=hoy())
        db.add(a)
        ajustes.append(a)
    w.estudiante.bienestar_asignado_id = w.bienestar.id
    db.commit()
    return plan, ajustes


def make_estado_plan(db) -> None:
    """Catalogo ESTADO_PLAN minimo (para estado_plan_resultante_id)."""
    if not db.query(EstadoPlan).first():
        for n in ("FINALIZADO",):
            db.add(EstadoPlan(nombre_estado=n))
        db.commit()


def make_estrategia_para(db, plan, ajuste) -> EstrategiaDua:
    cat = EstrategiaDuaCatalogo(
        codigo=f"TST-{ajuste.id}", nombre="Instrucciones en varios formatos", descripcion_pedagogica="x",
        principio="REPRESENTACION", pauta=1, escenarios=["AULA"], tipos_barrera=["SENSORIAL", "COMUNICATIVA"],
    )
    db.add(cat)
    db.flush()
    est = EstrategiaDua(plan_id=plan.id, nombre_estrategia=cat.nombre, descripcion="x", dimension_dua="MULTIPLES_MEDIOS_PRESENTACION",
                        estrategia_catalogo_id=cat.id, escenario="AULA")
    db.add(est)
    db.commit()
    return est


class Api:
    """Atajos de cliente: `api.put(user, url, json)`."""

    def __init__(self, client):
        self.c = client

    def get(self, user, url, **kw):
        return self.c.get(f"/api/v1{url}", headers=auth_headers(user), **kw)

    def post(self, user, url, json=None):
        return self.c.post(f"/api/v1{url}", headers=auth_headers(user), json=json)

    def put(self, user, url, json=None):
        return self.c.put(f"/api/v1{url}", headers=auth_headers(user), json=json)

    def patch(self, user, url, json=None):
        return self.c.patch(f"/api/v1{url}", headers=auth_headers(user), json=json)

    def delete(self, user, url):
        return self.c.delete(f"/api/v1{url}", headers=auth_headers(user))
