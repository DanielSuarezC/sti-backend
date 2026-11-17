"""Router SOLO para pruebas: expone los helpers de la base (deps/permisos) como endpoints para probarlos por HTTP."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import (
    Accion,
    Recurso,
    assert_can,
    get_db,
    require_consent,
    require_roles,
    require_roles_consent,
)
from app.core.pagination import PageParams, paginate
from app.models import Usuario
from app.models.enums import Rol

router = APIRouter(prefix="/_t")


@router.get("/propio")
def propio(user=Depends(require_consent)):
    return {"ok": True, "rol": str(user.rol)}


@router.get("/solo-admin")
def solo_admin(user=Depends(require_roles(Rol.ADMIN))):
    return {"ok": True}


@router.get("/bienestar-consent")
def bienestar_consent(user=Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    return {"ok": True}


@router.get("/estudiantes/{est_id}/{recurso}")
def ver(est_id: int, recurso: Recurso, accion: Accion = Accion.LEER, db: Session = Depends(get_db),
        user: Usuario = Depends(require_roles(*list(Rol)))):
    assert_can(db, user, est_id, recurso, accion)
    return {"ok": True}


@router.get("/usuarios")
def usuarios(params: PageParams = Depends(), db: Session = Depends(get_db)):
    return paginate(db, select(Usuario).order_by(Usuario.id), params, lambda u: {"id": u.id, "email": u.email})
