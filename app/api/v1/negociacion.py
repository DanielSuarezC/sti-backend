"""Router `negociacion`: desacuerdo del estudiante / TareaNegociacion (RF-25, D12).

# OWNER: slice C1
Objetar un ajuste se hace en `POST /planes/{id}/ajustes/{aid}/respuesta-estudiante` (abre el ciclo 1).
Aquí se listan, consultan, contraproponen, responden y cierran las negociaciones.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent, students_scope_criterion_db
from app.core.errors import Forbidden
from app.core.pagination import PageParams, paginate
from app.models.enums import EstadoTareaNegociacion, Rol
from app.models.plan import PlanMaarTea, TareaNegociacion
from app.models.usuarios import Estudiante, Usuario
from app.schemas.negociacion import CerrarNegociacionIn, ContrapropuestaIn, ResponderNegociacionIn
from app.services import negotiation as neg
from app.services import plan_common as common

router = APIRouter(prefix="/negociacion", tags=["negociacion"])

ROLES = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE)


def _cargar(db: Session, user: Usuario, tarea_id: int, accion: Accion = Accion.LEER):
    t = neg.get_tarea(db, tarea_id)
    plan = common.get_plan(db, t.plan_id)
    assert_can(db, user, plan.estudiante_id, Recurso.PLAN, accion)
    return t, plan


@router.get("")
def listar(db: Session = Depends(get_db), params: PageParams = Depends(), plan_id: int | None = None,
           estado: EstadoTareaNegociacion | None = None, estudiante_id: int | None = None,
           user: Usuario = Depends(require_roles_consent(*ROLES))):
    stmt = (select(TareaNegociacion).join(PlanMaarTea, PlanMaarTea.id == TareaNegociacion.plan_id)
            .join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id)
            .where(students_scope_criterion_db(db, user)))
    if plan_id:
        stmt = stmt.where(TareaNegociacion.plan_id == plan_id)
    if estado:
        stmt = stmt.where(TareaNegociacion.estado == estado)
    if estudiante_id:
        stmt = stmt.where(PlanMaarTea.estudiante_id == estudiante_id)
    stmt = stmt.order_by(TareaNegociacion.updated_at.desc(), TareaNegociacion.id.desc())
    return paginate(db, stmt, params, lambda t: neg.serializar(db, t))


@router.get("/{tarea_id}")
def ver(tarea_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*ROLES))):
    t, plan = _cargar(db, user, tarea_id)
    return neg.serializar(db, t, plan)


@router.post("/{tarea_id}/contrapropuesta")
def contrapropuesta(tarea_id: int, body: ContrapropuestaIn, request: Request, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Bienestar responde a la objeción; puede modificar el ajuste en el mismo acto (`cambios_ajuste`)."""
    t, plan = _cargar(db, user, tarea_id, Accion.ESCRIBIR)
    cambios = body.cambios_ajuste.model_dump(exclude_unset=True) if body.cambios_ajuste else None
    neg.contrapropuesta(db, t, user, body.propuesta, cambios, request)
    db.commit()
    return neg.serializar(db, t, plan)


@router.post("/{tarea_id}/responder")
def responder(tarea_id: int, body: ResponderNegociacionIn, request: Request, db: Session = Depends(get_db),
              user: Usuario = Depends(require_roles_consent(Rol.ESTUDIANTE))):
    """El estudiante acepta la contrapropuesta o la rechaza con una nueva objeción (siguiente ciclo o escalamiento)."""
    t, plan = _cargar(db, user, tarea_id, Accion.CONCERTAR)
    neg.responder(db, t, user, body.acepta, body.comentario, request)
    db.commit()
    return neg.serializar(db, t, plan)


@router.post("/{tarea_id}/cerrar")
def cerrar(tarea_id: int, body: CerrarNegociacionIn, request: Request, db: Session = Depends(get_db),
           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR))):
    """Cierra la negociación con la decisión (acuerdo, retiro del ajuste o decisión del Comité de mantenerlo)."""
    accion = Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.LEER
    t, plan = _cargar(db, user, tarea_id, accion)
    if str(user.rol) == Rol.COORDINADOR and t.estado != EstadoTareaNegociacion.ESCALADA_COMITE:
        raise Forbidden("El Coordinador solo cierra negociaciones escaladas al Comité de Inclusión.", "ROL_NO_PERMITIDO")
    neg.cerrar(db, t, user, body.resultado.value, body.resolucion, request)
    db.commit()
    return neg.serializar(db, t, plan)
