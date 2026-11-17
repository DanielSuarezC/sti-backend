"""Router F9 - Evaluacion de efectividad (M7). Rutas bajo `/planes/{plan_id}/evaluacion...`.

# OWNER: slice C2
Contrato completo en docs/api/slice_c2.md. La logica vive en `services/evaluacion.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.evaluacion import EvaluacionPatch
from app.services import evaluacion as svc
from app.services.seguimiento import get_plan_or_404

router = APIRouter(prefix="/planes", tags=["evaluacion"])

_LEER = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE, Rol.DOCENTE, Rol.FAMILIAR, Rol.ADMIN)  # la matriz rechaza a los demas


def _ctx(db: Session, user: Usuario, plan_id: int, accion: Accion = Accion.LEER):
    plan = get_plan_or_404(db, plan_id)
    est = assert_can(db, user, plan.estudiante_id, Recurso.EVALUACION, accion)
    return plan, est


@router.post("/{plan_id}/evaluacion", status_code=201)
def crear_borrador(plan_id: int, request: Request, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Crea el borrador consolidado de C1+C2+C3 (sintesis automatica por ajuste + indicadores D6/D8)."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    ev = svc.crear_borrador(db, plan, est, user, request)
    db.commit()
    return svc.serializar(db, plan, ev)


@router.get("/{plan_id}/evaluacion")
def ver(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*_LEER))):
    plan, _ = _ctx(db, user, plan_id)
    return svc.serializar(db, plan, svc.exigir_evaluacion(db, plan.id))


@router.patch("/{plan_id}/evaluacion")
def actualizar(plan_id: int, body: EvaluacionPatch, request: Request, db: Session = Depends(get_db),
               user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Guarda decisiones por ajuste (justificacion obligatoria), valoracion de las 9 dimensiones y textos del F9."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    ev = svc.exigir_evaluacion(db, plan.id)
    datos = body.model_dump(exclude_unset=True, exclude={"decisiones", "valoracion_dimensiones"})
    svc.patch(db, plan, est, ev, datos, body.decisiones, body.valoracion_dimensiones, user, request)
    db.commit()
    return svc.serializar(db, plan, ev)


@router.delete("/{plan_id}/evaluacion/decisiones/{decision_id}")
def quitar_decision(plan_id: int, decision_id: int, request: Request, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    svc.eliminar_decision(db, svc.exigir_evaluacion(db, plan.id), decision_id, user, est, request)
    db.commit()
    return {"detail": "Decisión archivada."}


@router.get("/{plan_id}/evaluacion/tendencia")
def ver_tendencia(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))):
    """Datos para el grafico de evolucion del semaforo (C1->C2->C3)."""
    plan, _ = _ctx(db, user, plan_id)
    return svc.tendencia(db, plan)


@router.post("/{plan_id}/evaluacion/cerrar")
def cerrar(plan_id: int, request: Request, db: Session = Depends(get_db),
           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Cierra el F9: exige C3 cerrado, decision en todos los ajustes y las 9 dimensiones. Plan -> FINALIZADO; alimenta el CBR."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    ev = svc.exigir_evaluacion(db, plan.id)
    res = svc.cerrar(db, plan, est, ev, user, request)
    db.commit()
    return {**res, "evaluacion": svc.serializar(db, plan, ev)}
