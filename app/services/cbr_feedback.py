"""Retroalimentacion del motor CBR (M3) al cerrar el F9: cada ajuste efectivo (ultimo semaforo VERDE) y su estrategia DUA
asociada quedan como CASO_CBR exitoso. El perfil es ANONIMO: tipos de barrera, escenarios, principios DUA y severidad.
Nunca se escribe nombre, AQ-10, diagnostico ni identificadores del estudiante.

# OWNER: slice C2
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dua import CasoCbr, EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import Semaforo
from app.models.mapa import BarreraIdentificada
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea

_SEV = {"LEVE": 0, "MODERADA": 1, "SEVERA": 2}


def _estrategia_para(db: Session, ajuste: AjusteRazonable, barrera: BarreraIdentificada | None,
                     estrategias: list[EstrategiaDua], catalogo: dict[int, EstrategiaDuaCatalogo]) -> EstrategiaDua | None:
    """1) la estrategia cuya sugerencia nacio de la misma barrera; 2) la del catalogo que atiende ese tipo de barrera
    (y escenario, si la barrera lo tiene)."""
    for e in estrategias:
        if e.sugerencia_id and barrera is not None:
            s = db.get(SugerenciaDua, e.sugerencia_id)
            if s is not None and s.barrera_id == barrera.id:
                return e
    if barrera is None:
        return None
    mejores: list[EstrategiaDua] = []
    for e in estrategias:
        cat = catalogo.get(e.estrategia_catalogo_id or -1)
        if cat is None or str(barrera.tipo_barrera) not in [str(t) for t in (cat.tipos_barrera or [])]:
            continue
        if barrera.escenario is not None and str(barrera.escenario) not in [str(x) for x in (cat.escenarios or [])]:
            continue
        mejores.append(e)
    return mejores[0] if mejores else None


def alimentar_cbr(db: Session, plan: PlanMaarTea, ajustes_verdes: list[tuple[AjusteRazonable, str | None]]) -> dict:
    """`ajustes_verdes`: [(ajuste, percepcion_ultima | None)] de los ajustes efectivos. Crea o actualiza los casos."""
    estrategias = list(db.scalars(select(EstrategiaDua).where(
        EstrategiaDua.plan_id == plan.id, EstrategiaDua.estrategia_catalogo_id.is_not(None))))
    catalogo = {c.id: c for c in db.scalars(select(EstrategiaDuaCatalogo).where(
        EstrategiaDuaCatalogo.id.in_({e.estrategia_catalogo_id for e in estrategias} or {-1})))}
    res = {"creados": 0, "actualizados": 0, "sin_estrategia": 0}
    for ajuste, percepcion in ajustes_verdes:
        barrera = db.get(BarreraIdentificada, ajuste.barrera_asociada_id)
        est = _estrategia_para(db, ajuste, barrera, estrategias, catalogo)
        if est is None:
            res["sin_estrategia"] += 1
            continue
        cat = catalogo[est.estrategia_catalogo_id]
        escenarios = sorted({str(x) for x in (est.escenario, barrera.escenario if barrera else None) if x})
        perfil = {
            "tipos_barrera": [str(barrera.tipo_barrera)] if barrera else [],
            "escenarios": escenarios,
            "principios": [str(cat.principio)],
            "severidad_max": str(barrera.severidad) if barrera else None,
            "tipo_ajuste": str(ajuste.tipo_ajuste),
        }
        peso = 1.0 if percepcion in (None, "POSITIVA") else 0.8
        caso = db.scalar(select(CasoCbr).where(CasoCbr.plan_id == plan.id, CasoCbr.estrategia_catalogo_id == cat.id,
                                               CasoCbr.origen == "F9"))
        if caso is None:
            db.add(CasoCbr(estrategia_catalogo_id=cat.id, perfil=perfil, resultado_semaforo=Semaforo.VERDE, exitoso=True,
                           peso=peso, semestre_academico=plan.semestre_academico, plan_id=plan.id, origen="F9",
                           fecha_caso=date.today()))
            res["creados"] += 1
        else:
            caso.perfil, caso.peso, caso.exitoso, caso.resultado_semaforo = perfil, peso, True, Semaforo.VERDE
            caso.fecha_caso = date.today()
            res["actualizados"] += 1
    db.flush()
    return res
