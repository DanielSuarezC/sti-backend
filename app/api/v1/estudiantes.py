"""Router estudiantes: tablero, resumen, «Mi ruta» (12 pasos), pendientes, asignacion de Bienestar e inasistencia.

# OWNER: slice C2
Contrato completo en docs/api/slice_c2.md. El listado NUNCA incluye AQ-10 ni datos clinicos.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import (
    Accion,
    Recurso,
    assert_can,
    get_db,
    get_own_estudiante,
    require_roles,
    require_roles_consent,
    students_scope_criterion_db,
)
from app.core.errors import Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams
from app.models.enums import EstadoPlanEnum, EstadoUsuario, Rol
from app.models.plan import PlanMaarTea
from app.models.usuarios import Estudiante, Usuario
from app.schemas.estudiantes import AsignarBienestar
from app.schemas.seguimiento import InasistenciaIn, InasistenciaSigaaIn
from app.services import inasistencia as inas
from app.services import ruta as ruta_svc

router = APIRouter(prefix="/estudiantes", tags=["estudiantes"])

_VISTA_LISTA = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ADMIN)


def _plan_exists(*conds):
    return exists().where(PlanMaarTea.estudiante_id == Estudiante.id, PlanMaarTea.deleted_at.is_(None),
                          PlanMaarTea.estado != EstadoPlanEnum.ARCHIVADO, *conds)


# ----------------------------------------------------------------------------- tablero
@router.get("")
def listar(
    q: str | None = Query(None, description="Texto: nombre o codigo"),
    estado: EstadoUsuario | None = Query(None, description="Estado de la cuenta"),
    estado_plan: EstadoPlanEnum | None = None,
    semaforo: Literal["VERDE", "AMARILLO", "ROJO", "SIN_SEMAFORO"] | None = Query(None, description="Semaforo agregado del plan"),
    con_pendientes: bool | None = Query(None, description="true = solo con pendientes; false = solo sin pendientes"),
    asignados_a_mi: bool = False,
    programa_id: int | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_roles_consent(*_VISTA_LISTA)),
):
    """Bienestar: sus estudiantes; Coordinador: su programa; Admin: todos. Paginado."""
    stmt = (select(Estudiante).join(Usuario, Usuario.id == Estudiante.usuario_id)
            .where(students_scope_criterion_db(db, user)))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Usuario.nombre_completo).like(like), func.lower(Estudiante.codigo_estudiante).like(like)))
    if estado:
        stmt = stmt.where(Usuario.estado == estado)
    if programa_id:
        stmt = stmt.where(Estudiante.programa_id == programa_id)
    if asignados_a_mi:
        stmt = stmt.where(Estudiante.bienestar_asignado_id == user.id)
    if estado_plan:
        stmt = stmt.where(_plan_exists(PlanMaarTea.estado == estado_plan))
    if semaforo == "SIN_SEMAFORO":
        stmt = stmt.where(~_plan_exists(PlanMaarTea.semaforo_actual.is_not(None)))
    elif semaforo:
        stmt = stmt.where(_plan_exists(PlanMaarTea.semaforo_actual == semaforo))
    stmt = stmt.order_by(Usuario.nombre_completo, Estudiante.id)
    rol = str(user.rol)

    def fila(e: Estudiante) -> dict:
        u = db.get(Usuario, e.usuario_id)
        if rol == Rol.ADMIN:  # el admin solo ve datos basicos (matriz §12.1)
            return {"id": e.id, "usuario_id": u.id, "nombre_completo": u.nombre_completo, "codigo_estudiante": e.codigo_estudiante,
                    "programa_id": e.programa_id, "estado_cuenta": str(u.estado), "estado_academico": str(e.estado_academico)}
        return ruta_svc.resumen_tablero(db, e, u, rol)

    if con_pendientes is None:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        page = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
        return {"items": [fila(e) for e in page], "total": total, "page": params.page, "page_size": params.page_size}
    filas = [fila(e) for e in db.scalars(stmt)]
    filas = [f for f in filas if (f.get("pendientes", 0) > 0) == con_pendientes]
    return {"items": filas[params.offset: params.offset + params.page_size], "total": len(filas),
            "page": params.page, "page_size": params.page_size}


# ----------------------------------------------------------------------------- mi ruta (estudiante)
@router.get("/mi-ruta")
def mi_ruta(db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    """Los 12 pasos del propio estudiante. No exige F0 firmado: si falta, «lo que sigue» lo lleva a firmarlo."""
    est = get_own_estudiante(db, user)
    if est is None:
        raise NotFound("No encontramos su perfil de estudiante.", "ESTUDIANTE_NO_ENCONTRADO")
    return ruta_svc.calcular_ruta(db, est, Rol.ESTUDIANTE)


def _est_para_ruta(db: Session, user: Usuario, estudiante_id: int) -> Estudiante:
    """Alcance (rol + vinculo) sin exigir F0: la ruta solo muestra estados, nunca contenido de los formatos."""
    return assert_can(db, user, estudiante_id, Recurso.DATOS_BASICOS, Accion.LEER, require_consent=False)


@router.get("/{estudiante_id}/ruta")
def ruta(estudiante_id: int, db: Session = Depends(get_db),
         user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))):
    est = _est_para_ruta(db, user, estudiante_id)
    return ruta_svc.calcular_ruta(db, est, user.rol)


@router.get("/{estudiante_id}/pendientes")
def pendientes(estudiante_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))):
    est = _est_para_ruta(db, user, estudiante_id)
    items = ruta_svc.pendientes(db, est, user.rol)
    return {"estudiante_id": est.id, "total": len(items), "items": items}


# ----------------------------------------------------------------------------- resumen
@router.get("/{estudiante_id}")
def resumen(estudiante_id: int, db: Session = Depends(get_db),
            user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ADMIN, Rol.ESTUDIANTE))):
    """Resumen segun el rol: Bienestar/Estudiante ven ademas el estado del AQ-10 (sin puntaje); Coordinador no; Admin solo datos basicos."""
    est = assert_can(db, user, estudiante_id, Recurso.DATOS_BASICOS, Accion.LEER, require_consent=False)
    u = db.get(Usuario, est.usuario_id)
    rol = str(user.rol)
    base = {"id": est.id, "usuario_id": u.id, "nombre_completo": u.nombre_completo, "email": u.email,
            "codigo_estudiante": est.codigo_estudiante, "programa_id": est.programa_id, "anio_ingreso": est.anio_ingreso,
            "semestre_actual": est.semestre_actual, "estado_cuenta": str(u.estado), "estado_academico": str(est.estado_academico),
            "via_ingreso": str(est.via_ingreso)}
    if rol == Rol.ADMIN:
        return base
    r = ruta_svc.calcular_ruta(db, est, rol)
    out = {**ruta_svc.resumen_tablero(db, est, u, rol), "email": u.email, "anio_ingreso": est.anio_ingreso,
           "consentimiento_firmado": r["previos"][0]["estado"] == "hecho", "ruta": r}
    if rol in (Rol.BIENESTAR, Rol.ESTUDIANTE):
        out["telefono"] = u.telefono
        out["contacto_emergencia"] = est.contacto_emergencia
        aq = next((p for p in r["previos"] if p["codigo"] == "AQ10"), None)
        out["aq10"] = {"aplicado": bool(aq and aq["estado"] == "hecho"), "ruta_activada": r.get("ruta_activada")}
    return out


# ----------------------------------------------------------------------------- asignacion de Bienestar
@router.put("/{estudiante_id}/bienestar")
def asignar_bienestar(estudiante_id: int, body: AsignarBienestar, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))):
    """Asigna (o libera con null) el profesional de Bienestar responsable del estudiante."""
    from app.core.permissions import can_access_student, get_estudiante_or_404

    est = get_estudiante_or_404(db, estudiante_id)
    if not can_access_student(db, user, estudiante_id):
        raise Forbidden("No tiene permiso sobre este estudiante.", "ACCESO_DENEGADO")
    destino = None
    if body.bienestar_usuario_id is not None:
        destino = db.get(Usuario, body.bienestar_usuario_id)
        if destino is None or str(destino.rol) != Rol.BIENESTAR or str(destino.estado) != EstadoUsuario.ACTIVO:
            raise Unprocessable("El usuario indicado no es un profesional de Bienestar activo.", "BIENESTAR_INVALIDO")
    anterior = est.bienestar_asignado_id
    est.bienestar_asignado_id = destino.id if destino else None
    audit.log(db, user, "ASIGNACION_BIENESTAR", "estudiante", est.id, {"de": anterior, "a": est.bienestar_asignado_id},
              request=request, estudiante_id=est.id)
    db.commit()
    return {"estudiante_id": est.id, "bienestar_asignado": {"id": destino.id, "nombre_completo": destino.nombre_completo} if destino else None}


# ----------------------------------------------------------------------------- inasistencia (RF-31)
@router.post("/{estudiante_id}/inasistencia", status_code=201)
def registrar_inasistencia(estudiante_id: int, body: InasistenciaIn, request: Request, db: Session = Depends(get_db),
                           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Registro manual. Si porcentaje >= umbral se envia el correo inmediato a Bienestar + Coordinador (1 vez por periodo)."""
    est = assert_can(db, user, estudiante_id, Recurso.SEGUIMIENTO, Accion.ESCRIBIR)
    out = inas.registrar(db, est, user, body.model_dump(exclude_none=True), request=request)
    db.commit()
    return out


@router.get("/{estudiante_id}/inasistencia")
def listar_inasistencia(estudiante_id: int, db: Session = Depends(get_db),
                        user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))):
    assert_can(db, user, estudiante_id, Recurso.SEGUIMIENTO, Accion.LEER)
    return {"umbral": float(inas.umbral(db)), "items": inas.listar(db, estudiante_id)}


@router.post("/{estudiante_id}/inasistencia/sigaa", status_code=201)
def inasistencia_sigaa(estudiante_id: int, request: Request, body: InasistenciaSigaaIn | None = None, db: Session = Depends(get_db),
                       user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Lee el porcentaje del SIGAA (desactivado por defecto: 501 SIGAA_NO_CONFIGURADO; si falla: 502 y registre manualmente)."""
    est = assert_can(db, user, estudiante_id, Recurso.SEGUIMIENTO, Accion.ESCRIBIR)
    semestre = (body.semestre_academico if body else None) or inas.semestre_por_defecto(db)
    pct = inas.consultar_sigaa(est.codigo_estudiante, semestre)
    out = inas.registrar(db, est, user, {"porcentaje_inasistencia": pct, "semestre_academico": semestre}, fuente="SIGAA", request=request)
    db.commit()
    return out
