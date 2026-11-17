"""Router del Familiar Autorizado (D9, HU-22/28, Ley 1996/2019).

# OWNER: slice C3
* El ESTUDIANTE otorga/revoca desde `/estudiantes/mi/familiares`.
* El FAMILIAR solo lee (`/familiar/...`): cualquier POST/PUT/PATCH/DELETE bajo `/familiar` responde 403.
Documentado en `docs/api/slice_c3.md`.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_own_estudiante, require_roles, require_roles_consent
from app.core.errors import Forbidden, NotFound
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.common import MessageResponse
from app.schemas.familiar import (
    AutorizacionOut,
    CaracterizacionFamiliarOut,
    EstudianteAutorizadoOut,
    FamiliarCrear,
    FamiliarPatch,
    PlanFamiliarOut,
    SeguimientoFamiliarOut,
)
from app.services import familiar as svc

# OWNER: slice C3
router = APIRouter(tags=["familiar"])

_estudiante = Depends(require_roles_consent(Rol.ESTUDIANTE))
_familiar = Depends(require_roles(Rol.FAMILIAR))


def _mi_estudiante(db: Session, user: Usuario):
    est = get_own_estudiante(db, user)
    if est is None:
        raise NotFound("No encontramos su perfil de estudiante.", "ESTUDIANTE_NO_ENCONTRADO")
    return est


# ----------------------------------------------------------------------------- Estudiante (HU-22)
@router.post("/estudiantes/mi/familiares", response_model=AutorizacionOut, status_code=201, tags=["estudiante-familiares"])
def otorgar(body: FamiliarCrear, request: Request, db: Session = Depends(get_db), user: Usuario = _estudiante):
    est = _mi_estudiante(db, user)
    a = svc.otorgar(db, est, user, body, request)
    db.commit()
    return svc.serializar_autorizacion(db, a)


@router.get("/estudiantes/mi/familiares", response_model=list[AutorizacionOut], tags=["estudiante-familiares"])
def listar(incluir_revocadas: bool = False, db: Session = Depends(get_db), user: Usuario = _estudiante):
    return svc.listar(db, _mi_estudiante(db, user), incluir_revocadas)


@router.patch("/estudiantes/mi/familiares/{autorizacion_id}", response_model=AutorizacionOut,
              tags=["estudiante-familiares"])
def actualizar(autorizacion_id: int, body: FamiliarPatch, request: Request, db: Session = Depends(get_db),
               user: Usuario = _estudiante):
    est = _mi_estudiante(db, user)
    a = svc.actualizar(db, est, svc.get_autorizacion_or_404(db, est, autorizacion_id), body, user, request)
    db.commit()
    return svc.serializar_autorizacion(db, a)


@router.delete("/estudiantes/mi/familiares/{autorizacion_id}", response_model=AutorizacionOut,
               tags=["estudiante-familiares"])
def revocar(autorizacion_id: int, request: Request, motivo: str | None = None, db: Session = Depends(get_db),
            user: Usuario = _estudiante):
    """Revoca (inmediato). No borra la fila: queda REVOCADA para trazabilidad."""
    est = _mi_estudiante(db, user)
    a = svc.revocar(db, est, svc.get_autorizacion_or_404(db, est, autorizacion_id), user, motivo, request)
    db.commit()
    return svc.serializar_autorizacion(db, a)


# ----------------------------------------------------------------------------- Familiar (HU-28): solo lectura
@router.get("/familiar/estudiantes", response_model=list[EstudianteAutorizadoOut])
def mis_estudiantes(db: Session = Depends(get_db), user: Usuario = _familiar):
    return svc.estudiantes_autorizados(db, user)


@router.get("/familiar/estudiantes/{estudiante_id}/plan", response_model=PlanFamiliarOut)
def plan(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = _familiar):
    out = svc.ver_plan(db, user, estudiante_id, request)
    db.commit()
    return out


@router.get("/familiar/estudiantes/{estudiante_id}/seguimiento", response_model=SeguimientoFamiliarOut)
def seguimiento(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = _familiar):
    out = svc.ver_seguimiento(db, user, estudiante_id, request)
    db.commit()
    return out


@router.get("/familiar/estudiantes/{estudiante_id}/caracterizacion", response_model=CaracterizacionFamiliarOut)
def caracterizacion(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = _familiar):
    out = svc.ver_caracterizacion(db, user, estudiante_id, request)
    db.commit()
    return out


@router.api_route("/familiar/{ruta:path}", methods=["POST", "PUT", "PATCH", "DELETE"], response_model=MessageResponse,
                  include_in_schema=False)
def solo_lectura(ruta: str, user: Usuario = _familiar):
    raise Forbidden("El acceso de familiar es solo de lectura: no puede crear, modificar ni eliminar nada.",
                    "FAMILIAR_SOLO_LECTURA")
