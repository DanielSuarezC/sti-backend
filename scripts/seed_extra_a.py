"""Datos semilla adicionales del slice A (idempotente). El orquestador lo cablea desde `seed.py`:

    from scripts.seed_extra_a import seed as seed_extra_a
    seed_extra_a(db)            # referencia (siempre) y demo (solo si `demo=True` o SEED_DEMO)

Referencia (siempre): parámetros propios del slice A (`reportes_k_minimo`, ...), instrucciones del AQ-10 y asignaturas
de ejemplo del programa Enfermería. Demo (solo con demo): una solicitud de ingreso pendiente y una referencia del programa.
Todo ficticio; nada de esto debe cargarse con datos reales.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.academico import Asignatura, ProgramaAcademico  # noqa: E402
from app.models.consentimiento import SolicitudIngreso  # noqa: E402
from app.models.enums import EstadoSolicitudIngreso  # noqa: E402
from app.models.sistema import ParametroSistema  # noqa: E402
from app.services import params, system_params  # noqa: E402
from app.services.aq10_config import INSTRUCCIONES_POR_DEFECTO, PARAM_INSTRUCCIONES  # noqa: E402

ASIGNATURAS = [
    ("ENF103", "Bases conceptuales del cuidado", 1, 3, False),
    ("ENF201", "Cuidado de la persona adulta", 3, 5, False),
    ("ENF701", "Práctica clínica integrada", 7, 8, True),
]


def seed(db: Session, demo: bool | None = None) -> dict:
    demo = get_settings().seed_demo if demo is None else demo
    out: dict = {"parametros": 0, "asignaturas": 0}
    existentes = set(db.scalars(select(ParametroSistema.clave)))
    for clave, spec in system_params.EXTRA.items():
        if clave not in existentes:
            valor = INSTRUCCIONES_POR_DEFECTO if clave == PARAM_INSTRUCCIONES else spec.default
            params.set_param(db, clave, valor, descripcion=spec.descripcion)
            out["parametros"] += 1
    prog = db.scalar(select(ProgramaAcademico).where(ProgramaAcademico.codigo_programa == "ENF"))
    if prog is not None:
        for codigo, nombre, sem, cred, practica in ASIGNATURAS:
            if not db.scalar(select(Asignatura.id).where(Asignatura.programa_id == prog.id, Asignatura.codigo == codigo)):
                db.add(Asignatura(programa_id=prog.id, codigo=codigo, nombre=nombre, semestre_plan=sem, creditos=cred,
                                  es_practica=practica))
                out["asignaturas"] += 1
        if demo:
            if not db.scalar(select(SolicitudIngreso.id).where(SolicitudIngreso.codigo_estudiantil == "DEMO-SOL-01")):
                db.add(SolicitudIngreso(
                    codigo_estudiantil="DEMO-SOL-01", email_institucional="solicitante.demo@sti-demo.example.com",
                    nombre_completo="Solicitante Uno (demo)", programa_id=prog.id, estado=EstadoSolicitudIngreso.PENDIENTE,
                    acepta_aviso_privacidad=True, verificada_directorio=False,
                ))
                out["solicitudes_demo"] = 1
            ref = params.get_param(db, f"referencia_programa:{prog.id}", None)
            if ref is None:
                params.set_param(db, f"referencia_programa:{prog.id}", {
                    "permanencia_pct": 82.0, "avance_promedio_pct": 45.0, "graduacion_pct": 58.0, "promedio_academico": 3.7,
                    "fuente": "Valores de ejemplo (demo): el administrador ingresa los reales"})
                out["referencia_demo"] = 1
    db.flush()
    return out


if __name__ == "__main__":
    from app.core.db import session_scope

    with session_scope() as s:
        print(seed(s))
