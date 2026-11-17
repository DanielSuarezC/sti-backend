"""Router `docente` (HU-23/24, D10): ajustes y estrategias DUA de SUS asignaturas, sin datos clinicos.

# OWNER: slice C3
Documentado en `docs/api/slice_c3.md`.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_roles
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.docente import (
    AjusteDetalleOut,
    EstrategiaImplementacionOut,
    ImplementacionAjusteIn,
    ImplementacionEstrategiaIn,
    ImplementacionOut,
    MisAjustesOut,
    SemaforoDocenteOut,
)
from app.services import docente_panel as svc

# OWNER: slice C3
router = APIRouter(prefix="/docente", tags=["docente"])

_docente = Depends(require_roles(Rol.DOCENTE))


@router.get("/mis-ajustes", response_model=MisAjustesOut)
def mis_ajustes(db: Session = Depends(get_db), user: Usuario = _docente):
    return svc.mis_ajustes(db, user)


@router.get("/semaforo", response_model=SemaforoDocenteOut)
def semaforo(db: Session = Depends(get_db), user: Usuario = _docente):
    return svc.semaforo(db, user)


@router.get("/ajustes/{ajuste_id}", response_model=AjusteDetalleOut)
def detalle_ajuste(ajuste_id: int, db: Session = Depends(get_db), user: Usuario = _docente):
    return svc.detalle_ajuste(db, user, ajuste_id)


@router.post("/ajustes/{ajuste_id}/implementacion", response_model=ImplementacionOut, status_code=201)
def registrar_implementacion(ajuste_id: int, body: ImplementacionAjusteIn, request: Request,
                             db: Session = Depends(get_db), user: Usuario = _docente):
    out = svc.registrar_implementacion(db, user, ajuste_id, body.implementado, body.fecha, body.nota, request)
    db.commit()
    return out


@router.get("/ajustes/{ajuste_id}/implementacion", response_model=list[ImplementacionOut])
def historial_implementacion(ajuste_id: int, db: Session = Depends(get_db), user: Usuario = _docente):
    return svc.historial_implementacion(db, user, ajuste_id)


@router.post("/estrategias/{estrategia_id}/implementacion", response_model=EstrategiaImplementacionOut)
def registrar_estrategia(estrategia_id: int, body: ImplementacionEstrategiaIn, request: Request,
                         db: Session = Depends(get_db), user: Usuario = _docente):
    out = svc.registrar_estrategia(db, user, estrategia_id, body.estado, body.fecha, body.nota, request)
    db.commit()
    return out
