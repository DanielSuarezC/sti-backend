"""Semilla extra del slice C3 (SOLO demo; requiere `SEED_DEMO=1 python -m scripts.seed` antes).

    python -m scripts.seed_extra_c3

Para est5 (datos FICTICIOS): trayectoria con dos semestres (2026-I cerrado y 2026-II en curso) con dimensiones e hitos,
un borrador de F10 (2026-II -> 2027-I) con una nota de continuidad PENDIENTE de aprobacion del estudiante, y una segunda
autorizacion de familiar (alcance: plan y notificaciones). Idempotente. `seed(db)` no hace commit.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.db import session_scope  # noqa: E402
from app.models import AutorizacionFamiliar, Estudiante, HitoTrayectoria, NotaContinuidad, Usuario  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.enums import EstadoAutorizacionFamiliar  # noqa: E402
from app.models.f10 import F10Semestre  # noqa: E402
from app.schemas.trayectoria import TrayectoriaCrear  # noqa: E402
from app.services import f10 as svc_f10  # noqa: E402
from app.services import trayectoria as svc_tray  # noqa: E402
from app.services.accounts import create_user  # noqa: E402

DOMAIN = "sti-demo.example.com"
NOTA_DEMO = "(Demo) Prefiere recibir las instrucciones por escrito y conocer los cambios de horario con una semana de anticipación."


def _usuario(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == email))


def seed(db: Session) -> dict:
    u5 = _usuario(db, f"est5.demo@{DOMAIN}")
    bienestar = _usuario(db, f"bienestar.demo@{DOMAIN}")
    if u5 is None or bienestar is None:
        return {"omitido": "faltan los usuarios demo: ejecute antes SEED_DEMO=1 python -m scripts.seed"}
    est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == u5.id))
    out: dict = {}

    # --- trayectoria: dos semestres
    if svc_tray.get_trayectoria(db, est.id, "2026-I") is None:
        svc_tray.crear_trayectoria(db, est, TrayectoriaCrear.model_validate({
            "semestre_academico": "2026-I", "fecha_inicio_semestre": "2026-02-02", "fecha_fin_semestre": "2026-06-06",
            "asignaturas_inscritas": 5, "asignaturas_completadas": 5, "creditos_aprobados": 17, "promedio_academico": 4.0,
            "dimensiones": {
                "ACCESO": {"puede_ingresar_aulas": True, "puede_acceder_plataforma": True},
                "PARTICIPACION": {"asistencia_promedio": 92.5, "participacion_clase": "MEDIA"},
                "APRENDIZAJE": {"demuestra_competencias": True, "calificaciones_promedio": 4.0},
                "BIENESTAR": {"percepcion_bienestar": "MEDIA", "siente_pertenencia": True},
                "AUTONOMIA": {"gestiona_su_agenda": True, "autorregulacion": "MEDIA"},
                "PERMANENCIA": {"continua_matriculado": True, "riesgo_desersion": "BAJO"},
                "PROGRESION": {"semestres_completados": 1, "avance_plan_estudios_porcentaje": 12},
            }}), bienestar)
        out["trayectoria_2026-I"] = 1
    if svc_tray.get_trayectoria(db, est.id, "2026-II") is None:
        svc_tray.crear_trayectoria(db, est, TrayectoriaCrear.model_validate({
            "semestre_academico": "2026-II", "fecha_inicio_semestre": "2026-08-03", "asignaturas_inscritas": 2,
            "creditos_aprobados": 8, "promedio_academico": 4.2,
            "dimensiones": {
                "PARTICIPACION": {"asistencia_promedio": 95, "participacion_clase": "ALTA", "trabajo_colaborativo": "CON_APOYO"},
                "BIENESTAR": {"percepcion_bienestar": "ALTA", "siente_pertenencia": True},
                "AUTONOMIA": {"gestiona_su_agenda": True, "solicita_apoyos_autonomamente": True},
                "PERMANENCIA": {"continua_matriculado": True, "riesgo_desersion": "BAJO"},
                "PROGRESION": {"semestres_completados": 2, "avance_plan_estudios_porcentaje": 25},
                "TRANSICION_PROFESIONAL": {"sector_interes_profesional": "Cuidado hospitalario"},
            }}), bienestar)
        out["trayectoria_2026-II"] = 1
    db.flush()

    # --- hitos
    t1 = svc_tray.get_trayectoria(db, est.id, "2026-I")
    t2 = svc_tray.get_trayectoria(db, est.id, "2026-II")
    if not db.scalars(select(HitoTrayectoria).where(HitoTrayectoria.estudiante_id == est.id)).first():
        for tray, tipo, fecha, desc in (
            (t1, "CAMBIO_SEMESTRE", date(2026, 6, 10), "(Demo) Cierre del primer semestre y paso a 2026-II."),
            (t2, "MATERIA_CLAVE", date(2026, 11, 20), "(Demo) Aprobó Anatomía y Fisiología."),
        ):
            db.add(HitoTrayectoria(estudiante_id=est.id, trayectoria_id=tray.id, tipo_hito=tipo, fecha_hito=fecha,
                                   descripcion=desc, registrado_por_id=bienestar.id))
        out["hitos"] = 2

    # --- F10 borrador + nota pendiente de aprobacion del estudiante
    f = db.scalar(select(F10Semestre).where(F10Semestre.estudiante_id == est.id, F10Semestre.semestre_origen == "2026-II"))
    if f is None:
        f = svc_f10.generar_borrador(db, est, bienestar, "2026-II", "2027-I")
        out["f10"] = f.id
    if not db.scalar(select(NotaContinuidad.id).where(NotaContinuidad.estudiante_id == est.id,
                                                      NotaContinuidad.semestre_origen == "2026-II")):
        nota = svc_f10.crear_nota(db, f, bienestar, NOTA_DEMO, "TODOS")
        svc_f10.enviar_nota(db, nota, bienestar, est)
        out["nota_pendiente"] = nota.id

    # --- segunda autorizacion de familiar (la primera, plan+seguimiento, viene de seed.py)
    email = f"familiar2.demo@{DOMAIN}"
    fam = _usuario(db, email)
    if fam is None:
        fam = create_user(db, email=email, nombre_completo="Gustavo Familiar (demo)", rol="FAMILIAR",
                          password=os.environ.get("DEMO_PASSWORD", "Demo-STI-2026!"), skip_password_policy=True)
    if not db.scalar(select(AutorizacionFamiliar.id).where(AutorizacionFamiliar.estudiante_id == est.id,
                                                           AutorizacionFamiliar.familiar_email == email)):
        db.add(AutorizacionFamiliar(
            estudiante_id=est.id, familiar_usuario_id=fam.id, familiar_nombre=fam.nombre_completo, familiar_email=email,
            parentesco="Padre (demo)", alcance=["PLAN", "NOTIFICACIONES"], estado=EstadoAutorizacionFamiliar.VIGENTE,
            otorgada_at=utcnow()))
        out["autorizacion_familiar"] = email
    db.flush()
    return out


def main() -> None:
    with session_scope() as db:
        print("Semilla C3:", seed(db))


if __name__ == "__main__":
    main()
