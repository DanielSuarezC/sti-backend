"""Semilla adicional del slice B (idempotente). NO edita `seed.py`.

    python -c "from app.core.db import session_scope; from scripts.seed_extra_b import seed; \
with session_scope() as db: print(seed(db))"

* Casos CBR ANÓNIMOS de demostración (`origen="SEED_DEMO"`): permiten que el motor M3 trabaje en modo CBR en la demo.
  No son datos reales de efectividad: reemplazar por los casos que genere el F9 en el piloto.
* Si existe el estudiante demo `est4` (F1 confirmada en `seed.py`), agrega F2 confirmada, 2 barreras, 1 facilitador y su
  vínculo, para poder recorrer el wizard F4/F5 y la generación de sugerencias DUA.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.models import (  # noqa: E402
    BarreraIdentificada,
    CasoCbr,
    EstrategiaDuaCatalogo,
    Estudiante,
    Facilitador,
    FacilitadorTecnologico,
    Usuario,
)
from app.models.caracterizacion import PerfilFortalezas  # noqa: E402
from app.models.enums import EstadoCaracterizacion  # noqa: E402
from app.models.slice_b import BarreraFacilitador, MetaEstudiante, PerfilFortalezasEstado  # noqa: E402

ORIGEN = "SEED_DEMO"
_SEMAFOROS = ["VERDE", "VERDE", "VERDE", "AMARILLO", "VERDE", "ROJO"]


def seed_cbr_cases(db: Session) -> int:
    if db.scalar(select(CasoCbr.id).where(CasoCbr.origen == ORIGEN).limit(1)):
        return 0
    n = 0
    for e in db.scalars(select(EstrategiaDuaCatalogo).order_by(EstrategiaDuaCatalogo.id)):
        for ti, tipo in enumerate((e.tipos_barrera or [])[:2]):
            for ei, esc in enumerate((e.escenarios or [])[:2]):
                for k in range(2):
                    sem = _SEMAFOROS[(e.id + ti + ei + k) % len(_SEMAFOROS)]
                    db.add(CasoCbr(
                        estrategia_catalogo_id=e.id, origen=ORIGEN, resultado_semaforo=sem, exitoso=sem != "ROJO",
                        peso=1.0, semestre_academico="2026-I", fecha_caso=date(2026, 6, 30),
                        perfil={"tipos_barrera": [tipo], "escenarios": [esc], "principios": [str(e.principio)],
                                "severidad_max": ["LEVE", "MODERADA", "SEVERA"][(k + ti) % 3], "rasgos": []},
                    ))
                    n += 1
    db.flush()
    return n


def seed_est4_mapa(db: Session) -> dict:
    u = db.scalar(select(Usuario).where(Usuario.email.like("est4.demo@%")))
    if u is None:
        return {}
    est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == u.id))
    if est is None or db.scalar(select(BarreraIdentificada.id).where(BarreraIdentificada.estudiante_id == est.id).limit(1)):
        return {}
    perfil = db.scalar(select(PerfilFortalezas).where(PerfilFortalezas.estudiante_id == est.id))
    if perfil is not None and db.scalar(select(PerfilFortalezasEstado.id).where(PerfilFortalezasEstado.perfil_fortalezas_id == perfil.id)) is None:
        if not db.scalar(select(MetaEstudiante.id).where(MetaEstudiante.perfil_fortalezas_id == perfil.id)):
            db.add(MetaEstudiante(perfil_fortalezas_id=perfil.id, tipo="PROFESIONAL", descripcion="(Demo) Graduarme y trabajar en cuidados intensivos.", plazo="5 años"))
        db.add(PerfilFortalezasEstado(perfil_fortalezas_id=perfil.id, estado=EstadoCaracterizacion.COMPLETA, confirmado_por_id=perfil.profesional_responsable_id))
    b1 = BarreraIdentificada(estudiante_id=est.id, tipo_barrera="SENSORIAL", escenario="AULA", fecha_identificacion=date(2026, 8, 14),
                             descripcion_barrera="(Demo) Aulas con ruido de pasillo y timbres que dificultan concentrarse.",
                             severidad="MODERADA", impacto_aprendizaje=True, semestre_academico="2026-II")
    b2 = BarreraIdentificada(estudiante_id=est.id, tipo_barrera="COMUNICATIVA", escenario="AULA", fecha_identificacion=date(2026, 8, 14),
                             descripcion_barrera="(Demo) Las instrucciones de trabajos se dan solo de forma oral.",
                             severidad="MODERADA", impacto_participacion=True, semestre_academico="2026-II")
    f = Facilitador(estudiante_id=est.id, tipo_facilitador="TECNOLOGICO", nombre_facilitador="(Demo) Audífonos con cancelación de ruido",
                    descripcion_detallada="Reducen el ruido de pasillo durante la clase.", fecha_identificacion=date(2026, 8, 14))
    db.add_all([b1, b2, f])
    db.flush()
    db.add(FacilitadorTecnologico(facilitador_id=f.id, tipo_tecnologia="Audífonos", funcionalidad_apoyo="Cancelación de ruido", disponibilidad="PERSONAL"))
    db.add(BarreraFacilitador(barrera_id=b1.id, facilitador_id=f.id))
    db.flush()
    return {"barreras": 2, "facilitadores": 1}


def seed(db: Session) -> dict:
    out = {"casos_cbr": seed_cbr_cases(db)}
    out.update(seed_est4_mapa(db))
    return out


if __name__ == "__main__":  # pragma: no cover
    from app.core.db import session_scope

    with session_scope() as _db:
        print(seed(_db))
