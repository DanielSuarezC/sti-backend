"""Utilidades comunes del Plan MAAR-TEA (slice C1): búsqueda, actores, bitácora de participación, calendario, avisos."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models.academico import CalendarioAcademico
from app.models.base import utcnow
from app.models.enums import EstadoUsuario, Rol
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea
from app.models.usuarios import CoordinadorPrograma, Estudiante, Usuario
from app.services.notifications import Evento, notify

logger = logging.getLogger("sti.plan")

# Acciones de auditoría propias del slice (LOG_AUDITORIA.accion es texto libre)
A_PLAN_CREADO = "PLAN_CREADO"
A_PLAN_EDITADO = "PLAN_EDITADO"
A_PLAN_ELIMINADO = "PLAN_ELIMINADO"
A_PLAN_ESTADO = "PLAN_CAMBIO_ESTADO"
A_PLAN_VERSION = "PLAN_NUEVA_VERSION"
A_PLAN_VISTO = "PLAN_CONSULTADO"
A_AJUSTE_CREADO = "AJUSTE_CREADO"
A_AJUSTE_EDITADO = "AJUSTE_EDITADO"
A_AJUSTE_ELIMINADO = "AJUSTE_ELIMINADO"
A_AJUSTE_RESPUESTA = "AJUSTE_RESPUESTA_ESTUDIANTE"
A_AJUSTE_DOCENTE = "AJUSTE_ACEPTACION_DOCENTE"
A_ESTRATEGIA_CREADA = "ESTRATEGIA_DUA_CREADA"
A_ESTRATEGIA_EDITADA = "ESTRATEGIA_DUA_EDITADA"
A_ESTRATEGIA_ELIMINADA = "ESTRATEGIA_DUA_ELIMINADA"
A_FIRMAS_INVALIDADAS = "FIRMAS_INVALIDADAS"
A_VERIFICACION = "PLAN_VERIFICADO"
A_MATRIZ_GENERADA = "MATRIZ_F7_GENERADA"
A_MATRIZ_EDITADA = "MATRIZ_F7_EDITADA"
A_NEGOCIACION = "NEGOCIACION"


def get_plan(db: Session, plan_id: int) -> PlanMaarTea:
    plan = db.get(PlanMaarTea, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise NotFound("No encontramos el Plan MAAR-TEA indicado.", "PLAN_NO_ENCONTRADO")
    return plan


def get_ajuste(db: Session, plan: PlanMaarTea, ajuste_id: int) -> AjusteRazonable:
    a = db.get(AjusteRazonable, ajuste_id)
    if a is None or a.deleted_at is not None or a.plan_id != plan.id:
        raise NotFound("No encontramos el ajuste razonable indicado en este plan.", "AJUSTE_NO_ENCONTRADO")
    return a


def get_estrategia(db: Session, plan: PlanMaarTea, estrategia_id: int) -> EstrategiaDua:
    e = db.get(EstrategiaDua, estrategia_id)
    if e is None or e.deleted_at is not None or e.plan_id != plan.id:
        raise NotFound("No encontramos la estrategia DUA indicada en este plan.", "ESTRATEGIA_NO_ENCONTRADA")
    return e


def estudiante_de(db: Session, plan: PlanMaarTea) -> Estudiante:
    return db.get(Estudiante, plan.estudiante_id)


def nombre_usuario(db: Session, usuario_id: int | None) -> str | None:
    if usuario_id is None:
        return None
    u = db.get(Usuario, usuario_id)
    return u.nombre_completo if u else None


def ref_usuario(db: Session, usuario_id: int | None) -> dict | None:
    """Referencia mínima {id, nombre_completo, rol} (sin correo ni documento)."""
    if usuario_id is None:
        return None
    u = db.get(Usuario, usuario_id)
    if u is None:
        return {"id": usuario_id, "nombre_completo": None, "rol": None}
    return {"id": u.id, "nombre_completo": u.nombre_completo, "rol": str(u.rol)}


def log_participacion(plan: PlanMaarTea, actor: Usuario | None, accion: str, entidad: str, entidad_id: int | None,
                      detalle: Any = None) -> None:
    """Agrega a la bitácora de participación del plan (D7): quién propuso, modificó, aceptó u objetó qué."""
    entrada = {
        "fecha": utcnow().isoformat(),
        "usuario_id": actor.id if actor else None,
        "rol": str(actor.rol) if actor else "SISTEMA",
        "accion": accion,
        "entidad": entidad,
        "entidad_id": entidad_id,
        "detalle": detalle,
    }
    plan.participacion_log = [*(plan.participacion_log or []), entrada]


# ----------------------------------------------------------------------------- actores y notificaciones
def coordinadores_usuarios(db: Session, programa_id: int | None) -> list[Usuario]:
    if programa_id is None:
        return []
    out: list[Usuario] = []
    for c in db.scalars(select(CoordinadorPrograma)):
        ids = set()
        for x in c.programa_responsable_ids or []:
            try:
                ids.add(int(x))
            except (TypeError, ValueError):
                continue
        if programa_id in ids:
            u = db.get(Usuario, c.usuario_id)
            if u is not None and str(u.estado) == EstadoUsuario.ACTIVO:
                out.append(u)
    return out


def actores_del_plan(db: Session, plan: PlanMaarTea) -> list[Usuario]:
    """Estudiante, Bienestar, Coordinador(es) del programa y docentes/responsables de ajustes y estrategias."""
    db.flush()
    est = estudiante_de(db, plan)
    ids: dict[int, Usuario] = {}

    def add(u: Usuario | None):
        if u is not None and u.id not in ids and str(u.estado) in (
            EstadoUsuario.ACTIVO, EstadoUsuario.PENDIENTE_CONSENTIMIENTO
        ):
            ids[u.id] = u

    add(db.get(Usuario, est.usuario_id))
    for uid in (plan.elaborado_por_id, plan.validado_por_id, est.bienestar_asignado_id, plan.aprobado_por_id,
                *(plan.profesionales_responsables_ids or [])):
        if uid:
            add(db.get(Usuario, int(uid)))
    for u in coordinadores_usuarios(db, est.programa_id):
        add(u)
    for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id)):
        if a.responsable_id:
            add(db.get(Usuario, a.responsable_id))
    for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id)):
        if e.responsable_implementacion_id:
            add(db.get(Usuario, e.responsable_implementacion_id))
    return list(ids.values())


def enlace_plan(rol: str, plan: PlanMaarTea) -> str:
    rol = str(rol)
    if rol == Rol.ESTUDIANTE:
        return "/estudiante/plan"
    if rol == Rol.COORDINADOR:
        return f"/coordinador/planes/{plan.id}"
    if rol == Rol.DOCENTE:
        return f"/docente/planes/{plan.id}"
    if rol == Rol.FAMILIAR:
        return "/familiar/plan"
    return f"/bienestar/planes/{plan.id}"


def notificar_plan(db: Session, evento: Evento, plan: PlanMaarTea, destinatarios: list[Usuario],
                   payload: dict | None = None) -> None:
    """`notify` por grupo de rol para que el `enlace` apunte a la pantalla del rol. Nunca lanza ni rompe el negocio."""
    grupos: dict[str, list[Usuario]] = defaultdict(list)
    for u in destinatarios:
        grupos[str(u.rol)].append(u)
    for rol, users in grupos.items():
        pl = {"plan_id": plan.id, "version": plan.version, "enlace": enlace_plan(rol, plan), **(payload or {})}
        try:
            with db.begin_nested():
                notify(db, evento, users, pl)
        except Exception:  # noqa: BLE001 - M10: las notificaciones no deben romper la operación
            logger.exception("No se pudo notificar %s", evento)


# ----------------------------------------------------------------------------- calendario
def calendario_para(db: Session, estudiante: Estudiante, semestre: str | None = None) -> CalendarioAcademico | None:
    """Calendario ACTIVO del semestre (el del programa del estudiante tiene prioridad sobre el institucional)."""
    stmt = select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True))
    if semestre:
        stmt = stmt.where(CalendarioAcademico.semestre_academico == semestre)
    cands = [c for c in db.scalars(stmt.order_by(CalendarioAcademico.fecha_inicio.desc()))
             if c.programa_id in (None, estudiante.programa_id)]
    cands.sort(key=lambda c: (c.programa_id is None,))  # específico del programa primero
    return cands[0] if cands else None
