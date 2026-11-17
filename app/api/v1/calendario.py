"""Calendario académico (cortes C1-C3, semestre activo) y parámetros del sistema (M1).

# OWNER: slice A. Lectura: cualquier usuario autenticado; escritura: Admin.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import get_current_user, get_db, require_roles
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.academico import CalendarioAcademico, ProgramaAcademico
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.calendario import CalendarioCreate, CalendarioUpdate, ParametroBody
from app.services import student_intake, system_params
from app.services.system_params import get_value

router = APIRouter(prefix="/calendario", tags=["calendario"])

ADMIN = Depends(require_roles(Rol.ADMIN))
LECTORES_PARAMS = Depends(require_roles(Rol.ADMIN, Rol.BIENESTAR))
SEMANAS = {"fecha_c1": (6, 7, "C1"), "fecha_c2": (11, 12, "C2"), "fecha_c3": (16, 17, "C3")}


def _out(c: CalendarioAcademico, advertencias: list[str] | None = None) -> dict:
    d = {
        "id": c.id, "semestre_academico": c.semestre_academico, "programa_id": c.programa_id,
        "fecha_inicio": c.fecha_inicio, "fecha_fin": c.fecha_fin, "fecha_c1": c.fecha_c1, "fecha_c2": c.fecha_c2,
        "fecha_c3": c.fecha_c3, "fecha_inicio_practicas": c.fecha_inicio_practicas,
        "umbral_inasistencia": float(c.umbral_inasistencia), "activo": bool(c.activo),
        "semanas_cortes": {k: (f"{(getattr(c, k) - c.fecha_inicio).days // 7 + 1}") for k in SEMANAS},
    }
    if advertencias is not None:
        d["advertencias"] = advertencias
    return d


def _validar(d: dict) -> list[str]:
    """Orden de fechas (error) y semanas aproximadas de cada corte (advertencia, no bloquea)."""
    i, f, c1, c2, c3 = d["fecha_inicio"], d["fecha_fin"], d["fecha_c1"], d["fecha_c2"], d["fecha_c3"]
    if not f > i:
        raise Unprocessable("La fecha de fin del semestre debe ser posterior a la de inicio.", "CALENDARIO_INVALIDO")
    if not (i < c1 < c2 < c3 <= f):
        raise Unprocessable("Los cortes deben ir en orden (C1 < C2 < C3) y dentro del semestre.", "CALENDARIO_INVALIDO")
    ip = d.get("fecha_inicio_practicas")
    if ip is not None and not i <= ip <= f:
        raise Unprocessable("El inicio de prácticas debe estar dentro del semestre.", "CALENDARIO_INVALIDO")
    avisos = []
    for k, (lo, hi, nombre) in SEMANAS.items():
        semana = (d[k] - i).days // 7 + 1
        if not lo <= semana <= hi:
            avisos.append(f"El corte {nombre} cae en la semana {semana}; lo habitual es la semana {lo} o {hi}.")
    return avisos


def _get(db: Session, cid: int) -> CalendarioAcademico:
    c = db.get(CalendarioAcademico, cid)
    if c is None:
        raise NotFound("No encontramos ese calendario.", "CALENDARIO_NO_ENCONTRADO")
    return c


def _check_programa(db: Session, programa_id: int | None) -> None:
    if programa_id is not None and db.get(ProgramaAcademico, programa_id) is None:
        raise Unprocessable("El programa indicado no existe.", "PROGRAMA_INVALIDO")


def _desactivar_otros(db: Session, c: CalendarioAcademico) -> None:
    for o in db.scalars(select(CalendarioAcademico).where(
        CalendarioAcademico.activo.is_(True), CalendarioAcademico.id != c.id,
        CalendarioAcademico.programa_id.is_(None) if c.programa_id is None else CalendarioAcademico.programa_id == c.programa_id,
    )):
        o.activo = False


# ----------------------------------------------------------------------------- parámetros (antes de /{id})
@router.get("/parametros")
def listar_parametros(db: Session = Depends(get_db), _=LECTORES_PARAMS):
    return {"items": system_params.list_params(db)}


@router.put("/parametros/{clave}")
def actualizar_parametro(clave: str, body: ParametroBody, request: Request, db: Session = Depends(get_db),
                         admin: Usuario = ADMIN):
    res = system_params.update_param(db, admin, clave, body.valor, request=request)
    db.commit()
    return res


# ----------------------------------------------------------------------------- calendario
@router.get("/activo")
def activo(programa_id: int | None = None, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    c = student_intake.semestre_activo(db, programa_id)
    if c is None:
        raise NotFound("Aún no hay un semestre activo configurado.", "SIN_SEMESTRE_ACTIVO")
    return _out(c)


@router.get("")
def listar(semestre: str | None = None, programa_id: int | None = None, solo_activos: bool = False,
           db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    stmt = select(CalendarioAcademico).order_by(CalendarioAcademico.fecha_inicio.desc(), CalendarioAcademico.id.desc())
    if semestre:
        stmt = stmt.where(CalendarioAcademico.semestre_academico == semestre)
    if programa_id is not None:
        stmt = stmt.where(CalendarioAcademico.programa_id == programa_id)
    if solo_activos:
        stmt = stmt.where(CalendarioAcademico.activo.is_(True))
    return {"items": [_out(c) for c in db.scalars(stmt)]}


@router.post("", status_code=201)
def crear(body: CalendarioCreate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    datos = body.model_dump()
    avisos = _validar(datos)
    _check_programa(db, body.programa_id)
    if db.scalar(select(CalendarioAcademico.id).where(
        CalendarioAcademico.semestre_academico == body.semestre_academico,
        CalendarioAcademico.programa_id.is_(None) if body.programa_id is None else CalendarioAcademico.programa_id == body.programa_id,
    )):
        raise Conflict("Ya existe un calendario para ese semestre y programa. Edítelo en lugar de crear otro.", "CALENDARIO_DUPLICADO")
    umbral = datos.pop("umbral_inasistencia")
    if umbral is None:
        umbral = get_value(db, "umbral_inasistencia")
    c = CalendarioAcademico(**datos, umbral_inasistencia=Decimal(str(umbral)))
    db.add(c)
    db.flush()
    if c.activo:
        _desactivar_otros(db, c)
    audit.log(db, admin, "CALENDARIO_CREADO", "calendario_academico", c.id,
              {"semestre": c.semestre_academico, "programa_id": c.programa_id, "activo": c.activo}, request=request)
    db.commit()
    return _out(c, avisos)


@router.patch("/{calendario_id}")
def editar(calendario_id: int, body: CalendarioUpdate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    c = _get(db, calendario_id)
    cambios = body.model_dump(exclude_unset=True)
    merged = {k: getattr(c, k) for k in ("fecha_inicio", "fecha_fin", "fecha_c1", "fecha_c2", "fecha_c3", "fecha_inicio_practicas")}
    merged.update({k: v for k, v in cambios.items() if k in merged})
    avisos = _validar(merged)
    for k, v in cambios.items():
        setattr(c, k, Decimal(str(v)) if k == "umbral_inasistencia" and v is not None else v)
    audit.log(db, admin, "CALENDARIO_MODIFICADO", "calendario_academico", c.id,
              {"campos": sorted(cambios), "fechas": {k: str(v) for k, v in cambios.items() if isinstance(v, date)}}, request=request)
    db.commit()
    return _out(c, avisos)


@router.post("/{calendario_id}/activar")
def activar(calendario_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    """Define el semestre activo (uno por programa; uno institucional). Desactiva el anterior del mismo ámbito."""
    c = _get(db, calendario_id)
    c.activo = True
    _desactivar_otros(db, c)
    audit.log(db, admin, "CALENDARIO_ACTIVADO", "calendario_academico", c.id, {"semestre": c.semestre_academico}, request=request)
    db.commit()
    return _out(c)


@router.delete("/{calendario_id}", status_code=204)
def archivar(calendario_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    c = _get(db, calendario_id)
    if c.activo:
        raise Conflict("No se puede archivar el semestre activo. Active otro primero.", "CALENDARIO_ACTIVO")
    c.soft_delete(admin.id, "Archivado por el administrador")
    audit.log(db, admin, "CALENDARIO_ARCHIVADO", "calendario_academico", c.id, request=request)
    db.commit()
    return Response(status_code=204)
