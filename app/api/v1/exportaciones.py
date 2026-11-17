"""Router `exportaciones`: exportación del Plan MAAR-TEA a PDF / Word / HTML imprimible (RF-27, RNF-03).

# OWNER: slice C1
Flujo: POST /planes/{id}/exportar -> EXPORTACION (SOLICITADA) -> tarea asíncrona -> LISTA -> GET .../descargar.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.planes import LECTORES_SIN_DOCENTE, cargar_plan
from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.core.errors import AppError, Conflict, NotFound
from app.core.pagination import PageParams, paginate
from app.models.enums import EstadoExportacion
from app.models.sistema import Exportacion
from app.models.usuarios import Usuario
from app.schemas.exportaciones import FormatoExportacion
from app.services import exports, storage

router = APIRouter(tags=["exportaciones"])


class Gone(AppError):
    status_code = 410
    default_code = "EXPORTACION_EXPIRADA"


def _out(e: Exportacion) -> dict:
    p = e.parametros or {}
    return {
        "id": e.id, "plan_id": e.plan_id, "estado": str(e.estado), "tipo": str(e.tipo), "formato": p.get("formato"),
        "formato_solicitado": p.get("formato_solicitado"), "version_plan": p.get("version"), "aviso": p.get("aviso"),
        "archivo_nombre": e.archivo_nombre, "content_type": e.content_type, "size_bytes": e.size_bytes, "error": e.error,
        "solicitada_por_id": e.solicitada_por_id, "created_at": e.created_at.isoformat(),
        "completada_at": e.completada_at.isoformat() if e.completada_at else None,
        "expira_at": e.expira_at.isoformat() if e.expira_at else None,
        "descarga": f"/api/v1/exportaciones/{e.id}/descargar" if e.estado == EstadoExportacion.LISTA else None,
    }


def _cargar(db: Session, user: Usuario, exportacion_id: int) -> Exportacion:
    e = db.get(Exportacion, exportacion_id)
    if e is None or e.deleted_at is not None or e.plan_id is None:
        raise NotFound("No encontramos esa exportación.", "EXPORTACION_NO_ENCONTRADA")
    if e.solicitada_por_id != user.id:
        assert_can(db, user, e.estudiante_id, Recurso.PLAN, Accion.LEER)  # también quien puede leer el plan
    return e


@router.post("/planes/{plan_id}/exportar", status_code=202)
def exportar(plan_id: int, request: Request, formato: FormatoExportacion = Query(FormatoExportacion.pdf),
             db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    """Solicita la exportación (asíncrona). Si no hay PDF disponible en el servidor se entrega HTML imprimible con `aviso`."""
    plan = cargar_plan(db, user, plan_id)
    exp = exports.solicitar(db, plan, user, formato.value, request)
    db.commit()
    exports.encolar(exp.id)
    db.refresh(exp)
    return _out(exp)


@router.get("/planes/{plan_id}/exportaciones")
def exportaciones_del_plan(plan_id: int, db: Session = Depends(get_db), params: PageParams = Depends(),
                           user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    plan = cargar_plan(db, user, plan_id)
    stmt = select(Exportacion).where(Exportacion.plan_id == plan.id).order_by(Exportacion.id.desc())
    return paginate(db, stmt, params, _out)


@router.get("/exportaciones/{exportacion_id}")
def estado_exportacion(exportacion_id: int, db: Session = Depends(get_db),
                       user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    return _out(_cargar(db, user, exportacion_id))


@router.get("/exportaciones/{exportacion_id}/descargar")
def descargar(exportacion_id: int, request: Request, db: Session = Depends(get_db),
              user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    """Descarga autenticada y auditada del archivo generado."""
    e = _cargar(db, user, exportacion_id)
    if e.estado == EstadoExportacion.EXPIRADA:
        raise Gone("La exportación expiró. Solicite una nueva desde el plan.", "EXPORTACION_EXPIRADA")
    if e.estado != EstadoExportacion.LISTA or not e.archivo_key:
        raise Conflict(f"La exportación aún no está lista (estado: {e.estado}). Consulte de nuevo en unos segundos.",
                       "EXPORTACION_NO_LISTA")
    audit.log(db, user, audit.Accion.EXPORTACION_DESCARGADA, "exportacion", e.id,
              {"plan_id": e.plan_id, "archivo": e.archivo_nombre}, request=request, estudiante_id=e.estudiante_id)
    db.commit()
    return storage.download_response(e.archivo_key, e.archivo_nombre or f"plan-{e.plan_id}", e.content_type)
