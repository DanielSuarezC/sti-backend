"""Reportes institucionales M9 (RF-36, HU-26/27): agregados con supresión de celdas n<k, sin identificadores.

# OWNER: slice A. Coordinador: solo sus programas; Admin: todos. Uso del sistema (HU-27): solo Admin.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import get_db, require_roles
from app.core.errors import NotFound
from app.models.academico import ProgramaAcademico
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.reportes import ReferenciaBody
from app.services import params, reports

router = APIRouter(prefix="/reportes", tags=["reportes"])

LECTORES = Depends(require_roles(Rol.ADMIN, Rol.COORDINADOR))
ADMIN = Depends(require_roles(Rol.ADMIN))


@router.get("/alcance")
def alcance(db: Session = Depends(get_db), user: Usuario = LECTORES):
    """Programas que el usuario puede consultar y parámetro k vigente."""
    progs = reports.resolve_scope(db, user, None)
    return {"k_minimo": reports.k_minimo(db), "programas": [{"id": p.id, "nombre": p.nombre_programa} for p in progs]}


@router.get("/dashboard")
def dashboard(programa_id: int | None = None, semestre: str | None = None, db: Session = Depends(get_db), user: Usuario = LECTORES):
    return reports.dashboard(db, user, programa_id, semestre)


@router.get("/trayectorias")
def trayectorias(
    programa_id: int | None = None, semestre: str | None = None, ref_permanencia: float | None = Query(None, ge=0, le=100),
    ref_avance: float | None = Query(None, ge=0, le=100), ref_graduacion: float | None = Query(None, ge=0, le=100),
    ref_promedio: float | None = Query(None, ge=0, le=5), db: Session = Depends(get_db), user: Usuario = LECTORES,
):
    """Los parámetros `ref_*` reemplazan, solo para esta consulta, la referencia guardada del programa."""
    override = {"permanencia_pct": ref_permanencia, "avance_promedio_pct": ref_avance, "graduacion_pct": ref_graduacion,
                "promedio_academico": ref_promedio}
    return reports.trayectorias(db, user, programa_id, semestre, override)


@router.get("/ajustes-frecuentes")
def ajustes(programa_id: int | None = None, semestre: str | None = None, top: int = Query(15, ge=1, le=50),
            db: Session = Depends(get_db), user: Usuario = LECTORES):
    return reports.ajustes_frecuentes(db, user, programa_id, semestre, top)


@router.get("/efectividad-dua")
def efectividad(programa_id: int | None = None, semestre: str | None = None, top: int = Query(20, ge=1, le=50),
                db: Session = Depends(get_db), user: Usuario = LECTORES):
    return reports.efectividad_dua(db, user, programa_id, semestre, top)


@router.get("/uso")
def uso(desde: date | None = None, hasta: date | None = None, db: Session = Depends(get_db), user: Usuario = ADMIN):
    return reports.uso(db, user, desde, hasta)


# ----------------------------------------------------------------------------- referencias del programa
@router.get("/referencias")
def listar_referencias(db: Session = Depends(get_db), user: Usuario = LECTORES):
    out = []
    for p in reports.resolve_scope(db, user, None):
        out.append({"programa_id": p.id, "programa": p.nombre_programa, **{k: None for k in reports.REFERENCIA_KEYS},
                    "fuente": None, **reports.get_referencia(db, p.id)})
    return {"items": out}


@router.put("/referencias/{programa_id}")
def guardar_referencia(programa_id: int, body: ReferenciaBody, request: Request, db: Session = Depends(get_db),
                       admin: Usuario = ADMIN):
    """El Admin ingresa los valores de referencia del programa (promedio institucional) para comparar la cohorte TEA."""
    if db.scalar(select(ProgramaAcademico.id).where(ProgramaAcademico.id == programa_id)) is None:
        raise NotFound("No encontramos ese programa.", "PROGRAMA_NO_ENCONTRADO")
    valor = body.model_dump()
    params.set_param(db, reports.referencia_clave(programa_id), valor,
                     descripcion="Referencia del programa para el reporte de trayectorias (la ingresa el administrador).")
    audit.log(db, admin, "PARAMETRO_MODIFICADO", "parametro_sistema", None,
              {"clave": reports.referencia_clave(programa_id), "nuevo": valor}, request=request)
    db.commit()
    return {"programa_id": programa_id, **valor}


# ----------------------------------------------------------------------------- exportación
@router.get("/{tipo}/export")
def exportar(tipo: str, request: Request, formato: str = Query("xlsx", pattern="^(pdf|xlsx)$"), programa_id: int | None = None,
             semestre: str | None = None, desde: date | None = None, hasta: date | None = None,
             db: Session = Depends(get_db), user: Usuario = LECTORES):
    if tipo not in reports.TIPOS:
        raise NotFound(f"No existe el reporte «{tipo}». Opciones: {', '.join(reports.TIPOS)}.", "REPORTE_NO_ENCONTRADO")
    data = reports.build_report(db, user, tipo, programa_id=programa_id, semestre=semestre, desde=desde, hasta=hasta)
    audit.log(db, user, audit.Accion.EXPORTACION_SOLICITADA, "reporte", None,
              {"tipo": tipo, "formato": formato, "programa_id": programa_id, "semestre": semestre}, request=request, commit=True)
    base = f"reporte_{tipo.replace('-', '_')}_{date.today().isoformat()}"
    if formato == "xlsx":
        return Response(reports.to_xlsx(tipo, data),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
    contenido, es_pdf = reports.to_pdf(tipo, data)
    if es_pdf:
        return Response(contenido, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'})
    return Response(contenido, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}.html"', "X-Export-Degradado": "html",
                             "X-Export-Aviso": "PDF no disponible en este servidor; se entrega HTML imprimible."})
