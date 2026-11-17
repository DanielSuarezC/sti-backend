"""Catálogo DUA (M1, RF-14, HU-01): CRUD, activar/inactivar, importación CSV/JSON con dry-run y exportación.

# OWNER: slice A. Lectura: Admin/Bienestar/Coordinador/Docente (no Estudiante); escritura: Admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import get_db, require_roles
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import PageParams
from app.data.dua_cast import PAUTAS
from app.models.dua import EstrategiaDuaCatalogo
from app.models.enums import Escenario, PrincipioDua, Rol, TipoBarrera
from app.models.usuarios import Usuario
from app.schemas.dua import EstrategiaCreate, EstrategiaUpdate
from app.services import dua_catalog

router = APIRouter(prefix="/catalogo-dua", tags=["catalogo-dua"])

ADMIN = Depends(require_roles(Rol.ADMIN))
LECTORES = Depends(require_roles(Rol.ADMIN, Rol.BIENESTAR, Rol.COORDINADOR, Rol.DOCENTE))
EXPORTADORES = Depends(require_roles(Rol.ADMIN, Rol.BIENESTAR, Rol.COORDINADOR))


def _get(db: Session, eid: int) -> EstrategiaDuaCatalogo:
    e = db.get(EstrategiaDuaCatalogo, eid)
    if e is None:
        raise NotFound("No encontramos esa estrategia del catálogo.", "ESTRATEGIA_NO_ENCONTRADA")
    return e


def _filtrar(db: Session, user: Usuario, principio, pauta, escenario, tipo_barrera, activa, q) -> list[EstrategiaDuaCatalogo]:
    stmt = select(EstrategiaDuaCatalogo).order_by(EstrategiaDuaCatalogo.pauta, EstrategiaDuaCatalogo.punto_verificacion,
                                                  EstrategiaDuaCatalogo.codigo)
    if principio:
        stmt = stmt.where(EstrategiaDuaCatalogo.principio == principio)
    if pauta:
        stmt = stmt.where(EstrategiaDuaCatalogo.pauta == pauta)
    if str(user.rol) != Rol.ADMIN:
        activa = True  # solo el administrador ve las inactivas
    if activa is not None:
        stmt = stmt.where(EstrategiaDuaCatalogo.activo.is_(activa))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(EstrategiaDuaCatalogo.nombre).like(like), func.lower(EstrategiaDuaCatalogo.codigo).like(like),
                              func.lower(EstrategiaDuaCatalogo.descripcion_pedagogica).like(like)))
    rows = list(db.scalars(stmt))
    if escenario:
        rows = [r for r in rows if str(escenario) in (r.escenarios or [])]
    if tipo_barrera:
        rows = [r for r in rows if str(tipo_barrera) in (r.tipos_barrera or [])]
    return rows


@router.get("/principios")
def principios(_=LECTORES):
    """Los 3 principios y 9 pautas CAST 2.2 (con puntos de verificación) para los selectores."""
    return {"principios": dua_catalog.principios_y_pautas(), "escenarios": [e.value for e in Escenario],
            "tipos_barrera": [t.value for t in TipoBarrera]}


@router.get("/estrategias")
def listar(
    principio: PrincipioDua | None = None, pauta: int | None = Query(None, ge=1, le=9), escenario: Escenario | None = None,
    tipo_barrera: TipoBarrera | None = None, activa: bool | None = None, q: str | None = None, params: PageParams = Depends(),
    db: Session = Depends(get_db), user: Usuario = LECTORES,
):
    rows = _filtrar(db, user, principio, pauta, escenario, tipo_barrera, activa, q)
    page = rows[params.offset: params.offset + params.page_size]
    return {"items": [dua_catalog.serialize(r) for r in page], "total": len(rows), "page": params.page,
            "page_size": params.page_size}


@router.get("/estrategias/exportar")
def exportar(formato: str = Query("json", pattern="^(json|csv)$"), principio: PrincipioDua | None = None,
             pauta: int | None = Query(None, ge=1, le=9), escenario: Escenario | None = None,
             tipo_barrera: TipoBarrera | None = None, activa: bool | None = None, request: Request = None,
             db: Session = Depends(get_db), user: Usuario = EXPORTADORES):
    rows = _filtrar(db, user, principio, pauta, escenario, tipo_barrera, activa, None)
    audit.log(db, user, audit.Accion.EXPORTACION_SOLICITADA, "estrategia_dua_catalogo", None,
              {"formato": formato, "filas": len(rows)}, request=request, commit=True)
    if formato == "csv":
        return Response(dua_catalog.export_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="catalogo_dua.csv"'})
    return Response(dua_catalog.export_json(rows), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="catalogo_dua.json"'})


@router.post("/estrategias/importar")
async def importar(
    request: Request, archivo: UploadFile = File(...), dry_run: bool = Query(True), actualizar_existentes: bool = Query(False),
    omitir_errores: bool = Query(False), db: Session = Depends(get_db), admin: Usuario = ADMIN,
):
    """CSV o JSON. `dry_run=true` (por defecto) valida sin escribir; repita con `dry_run=false` para importar."""
    contenido = await archivo.read()
    res = dua_catalog.import_catalog(db, admin, contenido, archivo.filename, archivo.content_type, dry_run=dry_run,
                                     actualizar_existentes=actualizar_existentes, omitir_errores=omitir_errores, request=request)
    db.commit()
    return res


@router.post("/estrategias", status_code=201)
def crear(body: EstrategiaCreate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    d, errs = dua_catalog.normalize_row({**body.model_dump(mode="json")})
    if errs:
        raise Unprocessable("; ".join(m for _, m in errs), "ESTRATEGIA_INVALIDA", extra={"errores": [
            {"campo": c, "mensaje": m} for c, m in errs]})
    if db.scalar(select(EstrategiaDuaCatalogo.id).where(EstrategiaDuaCatalogo.codigo == d["codigo"])):
        raise Conflict("Ya existe una estrategia con ese código.", "CODIGO_DUPLICADO")
    e = EstrategiaDuaCatalogo(**d)
    db.add(e)
    db.flush()
    audit.log(db, admin, "CATALOGO_DUA_CREADO", "estrategia_dua_catalogo", e.id, {"codigo": e.codigo}, request=request)
    db.commit()
    return dua_catalog.serialize(e)


@router.get("/estrategias/{estrategia_id}")
def ver(estrategia_id: int, db: Session = Depends(get_db), user: Usuario = LECTORES):
    e = _get(db, estrategia_id)
    if not e.activo and str(user.rol) != Rol.ADMIN:
        raise NotFound("No encontramos esa estrategia del catálogo.", "ESTRATEGIA_NO_ENCONTRADA")
    return dua_catalog.serialize(e)


@router.patch("/estrategias/{estrategia_id}")
def editar(estrategia_id: int, body: EstrategiaUpdate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    e = _get(db, estrategia_id)
    cambios = body.model_dump(mode="json", exclude_unset=True)
    actual = dua_catalog.serialize(e)
    merged = {**{k: actual[k] for k in dua_catalog.CAMPOS}, **cambios}
    d, errs = dua_catalog.normalize_row(merged)
    if "pauta" in cambios and "pauta_nombre" not in cambios:
        d["pauta_nombre"] = PAUTAS[d["pauta"]][1] if d["pauta"] else d["pauta_nombre"]
    if errs:
        raise Unprocessable("; ".join(m for _, m in errs), "ESTRATEGIA_INVALIDA", extra={"errores": [
            {"campo": c, "mensaje": m} for c, m in errs]})
    for k in cambios:
        setattr(e, k, d[k])
    if "pauta" in cambios and "pauta_nombre" not in cambios:
        e.pauta_nombre = d["pauta_nombre"]
    audit.log(db, admin, "CATALOGO_DUA_MODIFICADO", "estrategia_dua_catalogo", e.id, {"campos": sorted(cambios)}, request=request)
    db.commit()
    return dua_catalog.serialize(e)


def _set_activo(db: Session, admin: Usuario, eid: int, activo: bool, request: Request) -> dict:
    e = _get(db, eid)
    e.activo = activo
    audit.log(db, admin, "CATALOGO_DUA_ACTIVADO" if activo else "CATALOGO_DUA_INACTIVADO", "estrategia_dua_catalogo", e.id,
              request=request)
    db.commit()
    return dua_catalog.serialize(e)


@router.post("/estrategias/{estrategia_id}/activar")
def activar(estrategia_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    return _set_activo(db, admin, estrategia_id, True, request)


@router.post("/estrategias/{estrategia_id}/inactivar")
def inactivar(estrategia_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    return _set_activo(db, admin, estrategia_id, False, request)


@router.delete("/estrategias/{estrategia_id}", status_code=204)
def archivar(estrategia_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    """Archiva (soft delete) la estrategia: deja de aparecer en el catálogo. Para solo ocultarla use `inactivar`."""
    e = _get(db, estrategia_id)
    e.activo = False
    e.soft_delete(admin.id, "Archivada por el administrador")
    audit.log(db, admin, "CATALOGO_DUA_ARCHIVADO", "estrategia_dua_catalogo", e.id, request=request)
    db.commit()
    return Response(status_code=204)
