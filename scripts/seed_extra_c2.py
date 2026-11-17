"""Datos demo del slice C2 (solo ficticios). Requiere la demo base:  SEED_DEMO=1 python -m scripts.seed

    python -m scripts.seed_extra_c2

Para est5 (plan en IMPLEMENTACION): 3 ajustes con seguimiento C1 de semaforos MIXTOS (VERDE, AMARILLO y un ROJO con su
alerta RF-39 y la tarea de concertacion del amarillo), percepcion del estudiante en el ajuste verde, corte C1 cerrado
(el rojo bloquea abrir C2 hasta registrar el rediseno) y un F9 en BORRADOR. Usa los servicios reales, asi que genera las
notificaciones, la auditoria y los caches igual que la API. Idempotente.
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
from app.core.db import session_scope  # noqa: E402
from app.models import AjusteRazonable, BarreraIdentificada, Estudiante, PlanMaarTea, Seguimiento, Usuario  # noqa: E402
from app.models.enums import TipoAjuste, TipoBarrera  # noqa: E402
from app.services import evaluacion as ev_svc  # noqa: E402
from app.services import seguimiento as seg  # noqa: E402
from app.services import semaforo as sem  # noqa: E402

DOMAIN = "sti-demo.example.com"


def _user(db: Session, clave: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == f"{clave}.demo@{DOMAIN}"))


def seed(db: Session) -> dict:
    est_user, bienestar, docente = _user(db, "est5"), _user(db, "bienestar"), _user(db, "docente")
    if not (est_user and bienestar and docente):
        return {"omitido": "Cargue primero la demo base (SEED_DEMO=1 python -m scripts.seed)."}
    est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == est_user.id))
    plan = db.scalar(select(PlanMaarTea).where(PlanMaarTea.estudiante_id == est.id).order_by(PlanMaarTea.id))
    if plan is None:
        return {"omitido": "est5 no tiene plan."}
    if db.scalar(select(Seguimiento.id).where(Seguimiento.plan_id == plan.id)):
        return {"omitido": "est5 ya tiene seguimiento."}
    est.bienestar_asignado_id = bienestar.id

    a1 = db.scalar(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id))
    extras = []
    for nombre, tipo, barrera_tipo, desc in (
        ("Instrucciones escritas y literales", TipoAjuste.COMUNICACION, TipoBarrera.COMUNICATIVA,
         "(Demo) Las consignas de trabajos y laboratorios se entregan por escrito, sin ambigüedad."),
        ("Evaluación en aula separada", TipoAjuste.EVALUACION, TipoBarrera.EVALUATIVA,
         "(Demo) Presenta los parciales en un salón con menos estímulos."),
    ):
        b = BarreraIdentificada(estudiante_id=est.id, tipo_barrera=barrera_tipo, descripcion_barrera=f"(Demo) {nombre}",
                                fecha_identificacion=date(2026, 8, 14), semestre_academico=plan.semestre_academico,
                                registrada_por_id=bienestar.id)
        db.add(b)
        db.flush()
        a = AjusteRazonable(plan_id=plan.id, barrera_asociada_id=b.id, nombre_ajuste=nombre, descripcion_ajuste=desc,
                            justificacion="(Demo) Reduce la sobrecarga.", tipo_ajuste=tipo, fecha_inicio=date(2026, 8, 24),
                            asignatura_id=a1.asignatura_id, responsable_id=docente.id, estado="ACTIVO",
                            aceptado_por_estudiante=True)
        db.add(a)
        extras.append(a)
    db.flush()
    verde, amarillo, rojo = a1, extras[0], extras[1]

    s, _ = seg.abrir_corte(db, plan, est, "C1", bienestar, {
        "descripcion_situacion_actual": "(Demo) Primer corte: se adaptó bien a la rutina del semestre.",
        "dificultades_emergentes": "(Demo) Las evaluaciones en aula grande le generan ansiedad."})
    seg.registrar_ajuste(db, plan, est, s, verde, bienestar, {
        "semaforo": "VERDE", "implementado": True, "frecuencia_implementacion": "Todas las clases",
        "resultado_observado": "(Demo) Se sienta en las filas centrales y reporta menos distracción."})
    seg.registrar_ajuste(db, plan, est, s, amarillo, bienestar, {
        "semaforo": "AMARILLO", "implementado": True, "frecuencia_implementacion": "Algunas guías",
        "resultado_observado": "(Demo) Solo dos de cuatro docentes entregan la consigna por escrito."})
    seg.registrar_ajuste(db, plan, est, s, rojo, bienestar, {  # ROJO: dispara RF-39 (4 actores, push + correo)
        "semaforo": "ROJO", "implementado": False, "frecuencia_implementacion": "No se aplicó",
        "resultado_observado": "(Demo) No hay un salón disponible el día del parcial; el ajuste no se pudo cumplir."})
    # El plan de est5 (semilla C1) trae más ajustes que los tres de arriba: el corte solo cierra con todos valorados.
    ya = {verde.id, amarillo.id, rojo.id}
    for otro in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id)):
        if otro.id in ya:
            continue
        seg.registrar_ajuste(db, plan, est, s, otro, bienestar, {
            "semaforo": "VERDE", "implementado": True, "frecuencia_implementacion": "Según lo acordado",
            "resultado_observado": "(Demo) Se aplica según lo acordado y el estudiante lo reporta como útil."})
    seg.registrar_percepcion(db, plan, s, verde, est_user, "POSITIVA", "(Demo) Me ayuda a concentrarme.")
    seg.registrar_percepcion(db, plan, s, rojo, est_user, "NEGATIVA", "(Demo) Tuve que presentar en el aula grande.")
    seg.agregar_registro(db, s, {"tipo_registro": "ENTREVISTA", "descripcion_metodologia": "(Demo) Entrevista de 30 minutos."}, bienestar)
    seg.agregar_evidencia(db, s, {
        "tipo_evidencia": "ACADEMICA", "descripcion_evidencia": "(Demo) Promedio del primer corte.", "dato_cuantitativo": 4.1,
        "resultados": [{"dimension_resultado": "APRENDIZAJE", "indicador_especifico": "Promedio de notas", "porcentaje_cumplimiento": 82}]},
        bienestar)
    seg.cerrar_corte(db, plan, est, s, bienestar)
    ev = ev_svc.crear_borrador(db, plan, est, bienestar)
    db.flush()
    return {"plan_id": plan.id, "seguimiento": "C1 (cerrado)", "rojos_sin_rediseno": [r.ajuste_id for r in sem.rojos_sin_rediseno(db, plan.id)],
            "evaluacion_borrador_id": ev.id}


def main() -> None:
    with session_scope() as db:
        print(seed(db))


if __name__ == "__main__":
    main()
