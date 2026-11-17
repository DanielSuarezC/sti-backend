"""Router `planes`: Plan MAAR-TEA (F6), concertación, firmas, versiones y matriz de responsabilidades (F7).

# OWNER: slice C1
Contrato completo en `docs/api/slice_c1.md`. RBAC según arquitectura v7 §12.1 (`core.permissions.MATRIZ`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import (
    Accion,
    Recurso,
    assert_can,
    get_db,
    require_roles_consent,
    students_scope_criterion_db,
)
from app.core.errors import BadRequest, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.permissions import docente_plan_ids_stmt
from app.models.enums import EstadoPlanEnum, Rol
from app.models.plan import PlanMaarTea
from app.models.usuarios import Estudiante, Usuario
from app.schemas.planes import (
    AceptacionDocenteIn,
    AjusteCreate,
    AjusteUpdate,
    ApoyoUpdate,
    DevolverIn,
    EstrategiaCreate,
    EstrategiaUpdate,
    FirmarIn,
    MatrizGenerarIn,
    MotivoIn,
    PlanCreate,
    PlanUpdate,
    RespuestaEstudianteIn,
    ValidarIn,
)
from app.services import plan_builder as builder
from app.services import plan_common as common
from app.services import plan_signatures as sig
from app.services import plan_views as views
from app.services import plan_workflow as wf

router = APIRouter(tags=["planes"])

LECTORES = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE, Rol.DOCENTE, Rol.FAMILIAR)
LECTORES_SIN_DOCENTE = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE, Rol.FAMILIAR)


# ----------------------------------------------------------------------------- helpers de acceso
def cargar_plan(db: Session, user: Usuario, plan_id: int, accion: Accion = Accion.LEER) -> PlanMaarTea:
    """Plan + alcance + matriz §12.1 + F0. El docente solo accede a planes vigentes donde tiene ajustes."""
    plan = common.get_plan(db, plan_id)
    assert_can(db, user, plan.estudiante_id, Recurso.PLAN, accion)
    rol = str(user.rol)
    if rol in (Rol.ESTUDIANTE, Rol.FAMILIAR) and plan.estado == EstadoPlanEnum.BORRADOR:
        raise NotFound("El plan aún está en elaboración por Bienestar.", "PLAN_NO_ENCONTRADO")
    if rol == Rol.DOCENTE and plan.id not in set(db.scalars(docente_plan_ids_stmt(user))):
        raise Forbidden("No tiene ajustes ni responsabilidades en este plan.", "ACCESO_DENEGADO")
    return plan


def _resp_plan(plan: PlanMaarTea, version_antes: int | None = None) -> dict:
    return {"id": plan.id, "estado": str(plan.estado), "version": plan.version,
            "nueva_version": version_antes is not None and plan.version != version_antes}


def _scoped_plans(db: Session, user: Usuario):
    stmt = select(PlanMaarTea).join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id).where(
        students_scope_criterion_db(db, user))
    rol = str(user.rol)
    if rol == Rol.DOCENTE:
        stmt = stmt.where(PlanMaarTea.id.in_(docente_plan_ids_stmt(user)))
    if rol in (Rol.ESTUDIANTE, Rol.FAMILIAR):
        stmt = stmt.where(PlanMaarTea.estado != EstadoPlanEnum.BORRADOR)
    return stmt


def _familiar_filtra(db: Session, user: Usuario, stmt):
    """El familiar solo ve planes de estudiantes cuyo alcance PLAN autorizó."""
    if str(user.rol) != Rol.FAMILIAR:
        return stmt
    ids = [e for e in set(db.scalars(select(PlanMaarTea.estudiante_id))) if can_plan(db, user, e)]
    return stmt.where(PlanMaarTea.estudiante_id.in_(ids or [-1]))


def can_plan(db: Session, user: Usuario, estudiante_id: int) -> bool:
    from app.core.deps import can

    return can(db, user, estudiante_id, Recurso.PLAN, Accion.LEER)


# ----------------------------------------------------------------------------- borrador y listados
@router.post("/estudiantes/{estudiante_id}/planes", status_code=201)
def crear_borrador(estudiante_id: int, request: Request, body: PlanCreate | None = None, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Borrador asistido (RF-21): combina barreras F4, facilitadores F5, fortalezas F2 y sugerencias DUA aceptadas."""
    est = assert_can(db, user, estudiante_id, Recurso.PLAN, Accion.ESCRIBIR)
    body = body or PlanCreate()
    plan, avisos = builder.crear_borrador(
        db, est, user, semestre=body.semestre_academico, resumen_ejecutivo=body.resumen_ejecutivo,
        justificacion_apoyos=body.justificacion_apoyos, incluir_sugerencias=body.incluir_sugerencias, request=request)
    db.commit()
    return {"plan": views.serializar_plan(db, plan, user), "avisos": avisos}


@router.get("/estudiantes/{estudiante_id}/planes")
def planes_del_estudiante(estudiante_id: int, db: Session = Depends(get_db), params: PageParams = Depends(),
                          user: Usuario = Depends(require_roles_consent(*LECTORES))):
    assert_can(db, user, estudiante_id, Recurso.PLAN, Accion.LEER)
    stmt = _scoped_plans(db, user).where(PlanMaarTea.estudiante_id == estudiante_id).order_by(
        PlanMaarTea.semestre_academico.desc(), PlanMaarTea.id.desc())
    return paginate(db, stmt, params, lambda p: views.item_listado(db, p))


@router.get("/planes")
def listar_planes(
    db: Session = Depends(get_db), params: PageParams = Depends(),
    estado: EstadoPlanEnum | None = None, semestre_academico: str | None = None, estudiante_id: int | None = None,
    programa_id: int | None = None, q: str | None = Query(None, description="Nombre o código del estudiante"),
    user: Usuario = Depends(require_roles_consent(*LECTORES)),
):
    """Listado con filtros; el alcance depende del rol (programa, asignación, propio o autorizado)."""
    stmt = _familiar_filtra(db, user, _scoped_plans(db, user))
    if estado:
        stmt = stmt.where(PlanMaarTea.estado == estado)
    if semestre_academico:
        stmt = stmt.where(PlanMaarTea.semestre_academico == semestre_academico)
    if estudiante_id:
        stmt = stmt.where(PlanMaarTea.estudiante_id == estudiante_id)
    if programa_id:
        stmt = stmt.where(Estudiante.programa_id == programa_id)
    if q:
        stmt = stmt.join(Usuario, Usuario.id == Estudiante.usuario_id).where(
            Usuario.nombre_completo.ilike(f"%{q}%") | Estudiante.codigo_estudiante.ilike(f"%{q}%"))
    stmt = stmt.order_by(PlanMaarTea.updated_at.desc(), PlanMaarTea.id.desc())
    return paginate(db, stmt, params, lambda p: views.item_listado(db, p))


@router.get("/planes/mio")
def mi_plan(db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.ESTUDIANTE))):
    """Plan vigente del estudiante autenticado (el más reciente que no esté archivado ni en borrador)."""
    from app.core.permissions import get_own_estudiante

    est = get_own_estudiante(db, user)
    plan = None
    if est is not None:
        plan = db.scalar(select(PlanMaarTea).where(
            PlanMaarTea.estudiante_id == est.id,
            PlanMaarTea.estado.notin_((EstadoPlanEnum.BORRADOR, EstadoPlanEnum.ARCHIVADO))
        ).order_by(PlanMaarTea.semestre_academico.desc(), PlanMaarTea.id.desc()))
    if plan is None:
        raise NotFound("Todavía no tiene un Plan MAAR-TEA para revisar. Bienestar le avisará cuando esté listo.", "SIN_PLAN")
    return views.serializar_plan(db, plan, user)


@router.get("/planes/{plan_id}")
def ver_plan(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*LECTORES))):
    plan = cargar_plan(db, user, plan_id)
    return views.serializar_plan(db, plan, user)


@router.patch("/planes/{plan_id}")
def editar_plan(plan_id: int, body: PlanUpdate, request: Request, db: Session = Depends(get_db),
                user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    antes = plan.version
    builder.actualizar_plan(db, plan, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return {"plan": views.serializar_plan(db, plan, user), "cambio": _resp_plan(plan, antes)}


@router.delete("/planes/{plan_id}", status_code=204)
def eliminar_plan(plan_id: int, request: Request, motivo: str = Query(min_length=3, max_length=500),
                  db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Soft delete de un plan en BORRADOR."""
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    builder.eliminar_plan(db, plan, user, motivo, request)
    db.commit()


@router.post("/planes/{plan_id}/archivar")
def archivar_plan(plan_id: int, body: MotivoIn, request: Request, db: Session = Depends(get_db),
                  user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    wf.archivar(db, plan, user, body.motivo, request)
    db.commit()
    return _resp_plan(plan)


@router.post("/planes/{plan_id}/sugerencias/incorporar")
def incorporar_sugerencias(plan_id: int, request: Request, db: Session = Depends(get_db),
                           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Incorpora al plan las sugerencias DUA aceptadas después de crear el borrador."""
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    antes = plan.version
    n = builder.incorporar_sugerencias(db, plan, user, request)
    db.commit()
    return {"incorporadas": n, "plan": _resp_plan(plan, antes)}


# ----------------------------------------------------------------------------- estrategias DUA
@router.post("/planes/{plan_id}/estrategias-dua", status_code=201)
def crear_estrategia(plan_id: int, body: EstrategiaCreate, request: Request, db: Session = Depends(get_db),
                     user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    antes = plan.version
    e = builder.crear_estrategia(db, plan, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return {"estrategia": views.serializar_estrategia(db, e, docente=False), "plan": _resp_plan(plan, antes)}


@router.patch("/planes/{plan_id}/estrategias-dua/{estrategia_id}")
def editar_estrategia(plan_id: int, estrategia_id: int, body: EstrategiaUpdate, request: Request,
                      db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    e = common.get_estrategia(db, plan, estrategia_id)
    antes = plan.version
    builder.actualizar_estrategia(db, plan, e, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return {"estrategia": views.serializar_estrategia(db, e, docente=False), "plan": _resp_plan(plan, antes)}


@router.delete("/planes/{plan_id}/estrategias-dua/{estrategia_id}")
def eliminar_estrategia(plan_id: int, estrategia_id: int, request: Request, motivo: str = Query(min_length=3, max_length=500),
                        db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    e = common.get_estrategia(db, plan, estrategia_id)
    antes = plan.version
    builder.eliminar_estrategia(db, plan, e, user, motivo, request)
    db.commit()
    return {"plan": _resp_plan(plan, antes)}


# ----------------------------------------------------------------------------- ajustes razonables
@router.post("/planes/{plan_id}/ajustes", status_code=201)
def crear_ajuste(plan_id: int, body: AjusteCreate, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    antes = plan.version
    a = builder.crear_ajuste(db, plan, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return _ajuste_resp(db, plan, a, user, antes)


def _ajuste_resp(db: Session, plan: PlanMaarTea, a, user: Usuario, antes: int | None = None) -> dict:
    from app.services import negotiation

    tareas = {}
    for t in negotiation.tareas_del_plan(db, plan.id):
        if t.ajuste_id:
            tareas[t.ajuste_id] = {"id": t.id, "estado": str(t.estado), "ciclo": t.ciclo, "max_ciclos": negotiation.max_ciclos(db),
                                   "siguiente_accion": negotiation.siguiente_accion(t)}
    docente = str(user.rol) == Rol.DOCENTE
    return {"ajuste": views.serializar_ajuste(db, a, docente=docente, sem=views.semaforos(db, [a.id]), tareas=tareas),
            "plan": _resp_plan(plan, antes)}


@router.get("/planes/{plan_id}/ajustes/{ajuste_id}")
def ver_ajuste(plan_id: int, ajuste_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(require_roles_consent(*LECTORES))):
    plan = cargar_plan(db, user, plan_id)
    a = common.get_ajuste(db, plan, ajuste_id)
    if str(user.rol) == Rol.DOCENTE:
        from app.core.permissions import docente_ajuste_ids

        if a.id not in docente_ajuste_ids(db, user, plan.id):
            raise Forbidden("Este ajuste no corresponde a sus asignaturas ni a sus responsabilidades.", "AJUSTE_NO_ES_SUYO")
    return _ajuste_resp(db, plan, a, user)


@router.patch("/planes/{plan_id}/ajustes/{ajuste_id}")
def editar_ajuste(plan_id: int, ajuste_id: int, body: AjusteUpdate, request: Request, db: Session = Depends(get_db),
                  user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Editar un ajuste reinicia su revisión por el estudiante. En un plan aprobado abre una versión nueva."""
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    a = common.get_ajuste(db, plan, ajuste_id)
    antes = plan.version
    builder.actualizar_ajuste(db, plan, a, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return _ajuste_resp(db, plan, a, user, antes)


@router.delete("/planes/{plan_id}/ajustes/{ajuste_id}")
def eliminar_ajuste(plan_id: int, ajuste_id: int, request: Request, motivo: str = Query(min_length=3, max_length=500),
                    db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    a = common.get_ajuste(db, plan, ajuste_id)
    antes = plan.version
    builder.eliminar_ajuste(db, plan, a, user, motivo, request)
    db.commit()
    return {"plan": _resp_plan(plan, antes)}


# ----------------------------------------------------------------------------- workflow de concertación
@router.post("/planes/{plan_id}/enviar-a-estudiante")
def enviar_a_estudiante(plan_id: int, request: Request, db: Session = Depends(get_db),
                        user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    wf.enviar_a_estudiante(db, plan, user, request)
    db.commit()
    return _resp_plan(plan)


@router.post("/planes/{plan_id}/ajustes/{ajuste_id}/respuesta-estudiante")
def respuesta_estudiante(plan_id: int, ajuste_id: int, body: RespuestaEstudianteIn, request: Request,
                         db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.ESTUDIANTE))):
    """El estudiante acepta, propone una modificación (con texto) u objeta. Objetar abre una negociación (ciclo 1)."""
    plan = cargar_plan(db, user, plan_id, Accion.CONCERTAR)
    a = common.get_ajuste(db, plan, ajuste_id)
    res = wf.respuesta_estudiante(db, plan, a, user, body.respuesta.value, body.comentario, request)
    db.commit()
    return {**res, "plan": _resp_plan(plan), **_ajuste_resp(db, plan, a, user)}


@router.post("/planes/{plan_id}/enviar-a-validacion")
def enviar_a_validacion(plan_id: int, request: Request, db: Session = Depends(get_db),
                        user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Bienestar incorpora lo concertado y envía al Coordinador. Requiere todos los ajustes aceptados y sin negociaciones abiertas."""
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    wf.enviar_a_validacion(db, plan, user, request)
    db.commit()
    return _resp_plan(plan)


@router.post("/planes/{plan_id}/validar")
def validar(plan_id: int, request: Request, body: ValidarIn | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(require_roles_consent(Rol.COORDINADOR))):
    plan = cargar_plan(db, user, plan_id, Accion.VALIDAR)
    wf.validar(db, plan, user, body.comentario if body else None, request)
    db.commit()
    return {**_resp_plan(plan), "hash_version": (sig.version_activa(db, plan.id, plan.version).hash_snapshot)}


@router.post("/planes/{plan_id}/devolver")
def devolver(plan_id: int, body: DevolverIn, request: Request, db: Session = Depends(get_db),
             user: Usuario = Depends(require_roles_consent(Rol.COORDINADOR))):
    plan = cargar_plan(db, user, plan_id, Accion.VALIDAR)
    antes = plan.version
    wf.devolver(db, plan, user, body.comentarios, request)
    db.commit()
    return _resp_plan(plan, antes)


@router.post("/planes/{plan_id}/ajustes/{ajuste_id}/aceptacion-docente")
def aceptacion_docente(plan_id: int, ajuste_id: int, body: AceptacionDocenteIn, request: Request,
                       db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.DOCENTE))):
    plan = cargar_plan(db, user, plan_id, Accion.ACEPTAR_RESPONSABILIDAD)
    a = common.get_ajuste(db, plan, ajuste_id)
    wf.aceptacion_docente(db, plan, a, user, body.acepta, body.comentario, request)
    db.commit()
    return _ajuste_resp(db, plan, a, user)


@router.post("/planes/{plan_id}/iniciar-implementacion")
def iniciar_implementacion(plan_id: int, request: Request, db: Session = Depends(get_db),
                           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan = cargar_plan(db, user, plan_id, Accion.ESCRIBIR)
    wf.iniciar_implementacion(db, plan, user, request)
    db.commit()
    return _resp_plan(plan)


# ----------------------------------------------------------------------------- firmas
@router.post("/planes/{plan_id}/firmar", status_code=201)
def firmar(plan_id: int, body: FirmarIn, request: Request, db: Session = Depends(get_db),
           user: Usuario = Depends(require_roles_consent(Rol.ESTUDIANTE, Rol.BIENESTAR, Rol.COORDINADOR))):
    """Cada actor firma solo con su cuenta. Con las tres firmas el plan queda APROBADO."""
    plan = cargar_plan(db, user, plan_id, Accion.FIRMAR)
    if not body.confirmo:
        raise Unprocessable("Confirme que leyó el plan para poder firmarlo.", "CONFIRMACION_REQUERIDA")
    res = sig.firmar(db, plan, user, request)
    db.commit()
    return {"firma": views.serializar_firma(db, res["firma"]), "aprobado": res["aprobado"], "matriz": res["matriz"],
            "firmas_estado": sig.estado_firmas(db, plan), "plan": _resp_plan(plan)}


@router.get("/planes/{plan_id}/firmas")
def listar_firmas(plan_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    plan = cargar_plan(db, user, plan_id)
    return {"plan_id": plan.id, "version": plan.version, "estado_firmas": sig.estado_firmas(db, plan),
            "firmas": [views.serializar_firma(db, f) for f in sig.firmas_de(db, plan.id)]}


@router.get("/planes/{plan_id}/verificar")
def verificar(plan_id: int, request: Request, db: Session = Depends(get_db),
              user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    """Recalcula el hash SHA-256 del contenido y lo compara con lo firmado."""
    plan = cargar_plan(db, user, plan_id)
    res = sig.verificar(db, plan)
    audit.log(db, user, common.A_VERIFICACION, "plan_maar_tea", plan.id, {"integro": res["integro"]}, request=request,
              estudiante_id=plan.estudiante_id)
    db.commit()
    return res


# ----------------------------------------------------------------------------- versiones
def _version_dict(db: Session, plan: PlanMaarTea, pv, *, con_snapshot: bool) -> dict:
    firmas = [views.serializar_firma(db, f) for f in sig.firmas_de(db, plan.id, pv.version)]
    out = {
        "version": pv.version, "vigente": pv.version == plan.version, "congelada": True, "reemplazada": pv.deleted_at is not None,
        "motivo_reemplazo": pv.deleted_reason, "estado_plan": pv.estado_plan, "hash_snapshot": pv.hash_snapshot,
        "motivo_cambio": pv.motivo_cambio, "creado_por": common.ref_usuario(db, pv.creado_por_id),
        "created_at": pv.created_at.isoformat(), "firmas": firmas,
    }
    if con_snapshot:
        out["snapshot"] = pv.snapshot
    return out


def _versiones(db: Session, plan: PlanMaarTea) -> dict[int, object]:
    por_version: dict[int, object] = {}
    for pv in wf.versiones_de(db, plan):  # orden por version, id: el último gana (el activo es el más reciente)
        por_version[pv.version] = pv
    return por_version


@router.get("/planes/{plan_id}/versiones")
def listar_versiones(plan_id: int, db: Session = Depends(get_db),
                     user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    plan = cargar_plan(db, user, plan_id)
    por_v = _versiones(db, plan)
    items = [_version_dict(db, plan, pv, con_snapshot=False) for pv in por_v.values()]
    if plan.version not in por_v:
        items.append({"version": plan.version, "vigente": True, "congelada": False, "reemplazada": False,
                      "motivo_reemplazo": None, "estado_plan": str(plan.estado),
                      "hash_snapshot": sig.hash_contenido(sig.contenido_canonico(db, plan)), "motivo_cambio": None,
                      "creado_por": None, "created_at": plan.updated_at.isoformat(), "firmas": []})
    items.sort(key=lambda x: x["version"], reverse=True)
    return {"plan_id": plan.id, "version_actual": plan.version, "items": items}


@router.get("/planes/{plan_id}/versiones/{numero}")
def ver_version(plan_id: int, numero: int, db: Session = Depends(get_db),
                user: Usuario = Depends(require_roles_consent(*LECTORES_SIN_DOCENTE))):
    plan = cargar_plan(db, user, plan_id)
    pv = _versiones(db, plan).get(numero)
    if pv is not None:
        return _version_dict(db, plan, pv, con_snapshot=True)
    if numero == plan.version:
        contenido = sig.contenido_canonico(db, plan)
        return {"version": numero, "vigente": True, "congelada": False, "reemplazada": False, "motivo_reemplazo": None,
                "estado_plan": str(plan.estado), "hash_snapshot": sig.hash_contenido(contenido), "motivo_cambio": None,
                "creado_por": None, "created_at": plan.updated_at.isoformat(), "firmas": [], "snapshot": contenido}
    raise NotFound("No existe esa versión del plan.", "VERSION_NO_ENCONTRADA")


# ----------------------------------------------------------------------------- F7: matriz de responsabilidades
def _escritor_matriz(db: Session, user: Usuario, plan: PlanMaarTea) -> None:
    if str(user.rol) == Rol.BIENESTAR:
        assert_can(db, user, plan.estudiante_id, Recurso.PLAN, Accion.ESCRIBIR)
    else:  # Coordinador del programa
        assert_can(db, user, plan.estudiante_id, Recurso.PLAN, Accion.LEER)


@router.post("/planes/{plan_id}/matriz", status_code=201)
def generar_matriz(plan_id: int, request: Request, body: MatrizGenerarIn | None = None, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR))):
    """Genera/sincroniza la F7 desde el plan aprobado. Fechas ligadas al calendario activo (409 si no hay)."""
    plan = common.get_plan(db, plan_id)
    _escritor_matriz(db, user, plan)
    builder.generar_matriz(db, plan, user, request=request, sobrescribir=bool(body and body.sobrescribir))
    db.commit()
    return builder.matriz_de(db, plan)


@router.get("/planes/{plan_id}/matriz")
def ver_matriz(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*LECTORES))):
    plan = cargar_plan(db, user, plan_id)
    if str(user.rol) == Rol.DOCENTE:
        from app.core.permissions import docente_ajuste_ids, docente_asignatura_ids_stmt
        from app.models.plan import EstrategiaDua

        aj = docente_ajuste_ids(db, user, plan.id)
        asig = set(db.scalars(docente_asignatura_ids_stmt(user)))
        es = {e.id for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id))
              if e.asignatura_id in asig or e.responsable_implementacion_id == user.id}
        return builder.matriz_de(db, plan, ajuste_ids=aj, estrategia_ids=es)
    return builder.matriz_de(db, plan)


@router.patch("/planes/{plan_id}/matriz/apoyos/{apoyo_id}")
def editar_apoyo(plan_id: int, apoyo_id: int, body: ApoyoUpdate, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR))):
    plan = common.get_plan(db, plan_id)
    _escritor_matriz(db, user, plan)
    datos = body.model_dump(exclude_unset=True)
    if not datos:
        raise BadRequest("Indique al menos un campo para modificar.", "SIN_CAMBIOS")
    builder.actualizar_apoyo(db, plan, apoyo_id, user, datos, request)
    db.commit()
    return builder.matriz_de(db, plan)


@router.get("/planes/{plan_id}/implementacion")
def tasa_implementacion(plan_id: int, corte: str | None = Query(None, pattern="^(C1|C2|C3)$"),
                        db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR))):
    """Tasa de implementación (D6: meta >= 80 % al C2) calculada desde los registros de implementación."""
    plan = cargar_plan(db, user, plan_id)
    return builder.resumen_implementacion(db, plan.id, corte)
