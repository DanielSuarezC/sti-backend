"""Workflow de concertación del Plan MAAR-TEA (RF-23, HU-19, HU-25).

    Bienestar propone  ->  Estudiante revisa ajuste por ajuste (acepta / propone modificación / objeta)
    ->  Bienestar incorpora  ->  Coordinador valida o devuelve  ->  firmas (estudiante, Bienestar, coordinador)
    ->  APROBADO  ->  docentes aceptan sus responsabilidades  ->  IMPLEMENTACION

Toda transición pasa por `plan_states.assert_transition` (409 `TRANSICION_PLAN_INVALIDA`). Editar un plan que ya pasó a
validación/firmas/aprobado reabre la concertación: `preparar_edicion` crea una versión nueva cuando hay firmas o el plan
ya estaba aprobado, e invalida las firmas de la versión anterior.
"""

from __future__ import annotations

from datetime import date

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, Unprocessable
from app.core.permissions import docente_ajuste_ids
from app.models.base import utcnow
from app.models.enums import (
    EstadoAjuste,
    EstadoPlanEnum,
    EstadoTareaNegociacion,
    Rol,
    RolFirmante,
)
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea, PlanVersion, TareaNegociacion
from app.models.usuarios import Usuario
from app.services import plan_common as common
from app.services import plan_signatures as sig
from app.services.notifications import Evento
from app.services.plan_states import ESTADOS_EDITABLES, ESTADOS_VIGENTES, assert_transition

S = EstadoPlanEnum
ESTADOS_TAREA_ABIERTA = (EstadoTareaNegociacion.ABIERTA, EstadoTareaNegociacion.EN_CICLO,
                         EstadoTareaNegociacion.ESCALADA_COMITE)


class Respuesta:
    ACEPTADO = "ACEPTADO"
    MODIFICACION_PROPUESTA = "MODIFICACION_PROPUESTA"
    OBJETADO = "OBJETADO"


# ----------------------------------------------------------------------------- transiciones
def cambiar_estado(db: Session, plan: PlanMaarTea, destino: EstadoPlanEnum, actor: Usuario | None,
                   request: Request | None = None, **detalle) -> None:
    assert_transition(plan.estado, destino)
    anterior = plan.estado
    plan.estado = destino
    db.flush()
    audit.log(db, actor, common.A_PLAN_ESTADO, "plan_maar_tea", plan.id,
              {"de": str(anterior), "a": str(destino), "version": plan.version, **detalle}, request=request,
              estudiante_id=plan.estudiante_id)


def tareas_abiertas(db: Session, plan_id: int, ajuste_id: int | None = None) -> list[TareaNegociacion]:
    db.flush()
    stmt = select(TareaNegociacion).where(TareaNegociacion.plan_id == plan_id,
                                          TareaNegociacion.estado.in_(ESTADOS_TAREA_ABIERTA))
    if ajuste_id is not None:
        stmt = stmt.where(TareaNegociacion.ajuste_id == ajuste_id)
    return list(db.scalars(stmt.order_by(TareaNegociacion.id)))


# ----------------------------------------------------------------------------- versiones y edición
def nueva_version(db: Session, plan: PlanMaarTea, actor: Usuario | None, motivo: str | None,
                  request: Request | None = None) -> int:
    """Abre la versión N+1: invalida firmas de N, conserva el snapshot de N (soft delete) y registra el motivo."""
    if sig.version_activa(db, plan.id, plan.version) is None:
        sig.congelar_version(db, plan, actor)  # asegura el historial de la versión que se cierra
    sig.invalidar_firmas(db, plan, actor, motivo or "Nueva versión del plan", request)
    previa = sig.version_activa(db, plan.id, plan.version)
    if previa is not None:
        previa.soft_delete(actor.id if actor else None, f"Reemplazada por la versión {plan.version + 1}")
    plan.version += 1
    common.log_participacion(plan, actor, "NUEVA_VERSION", "plan", plan.id,
                             {"version": plan.version, "motivo": motivo or "Modificación del plan"})
    audit.log(db, actor, common.A_PLAN_VERSION, "plan_maar_tea", plan.id,
              {"version": plan.version, "motivo": motivo}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return plan.version


def preparar_edicion(db: Session, plan: PlanMaarTea, actor: Usuario | None, motivo: str | None = None,
                     request: Request | None = None) -> bool:
    """Llamar ANTES de toda modificación del contenido. Devuelve True si abrió una versión nueva.

    * BORRADOR / EN_CONCERTACION / EN_NEGOCIACION / ESCALADO_COMITE: se edita la versión vigente.
    * PENDIENTE_VALIDACION: la edición reabre la concertación (el estudiante debe volver a revisar).
    * PENDIENTE_FIRMAS: si ya hay firmas se abre una versión nueva (firmas previas quedan INVALIDADAS).
    * APROBADO / IMPLEMENTACION / SEGUIMIENTO: nueva versión, nunca sobrescribe.
    * FINALIZADO / ARCHIVADO: 409 `PLAN_NO_EDITABLE`.
    """
    est = plan.estado
    if est in (S.FINALIZADO, S.ARCHIVADO):
        raise Conflict(f"El plan está {est} y ya no se puede modificar.", "PLAN_NO_EDITABLE")
    if est in ESTADOS_EDITABLES:
        return False
    abrio = False
    if est == S.PENDIENTE_VALIDACION:
        pass
    elif est == S.PENDIENTE_FIRMAS:
        if sig.firmas_de(db, plan.id, plan.version, solo_vigentes=True):
            abrio = bool(nueva_version(db, plan, actor, motivo, request))
        else:
            snap = sig.version_activa(db, plan.id, plan.version)
            if snap is not None:
                snap.soft_delete(actor.id if actor else None, "Snapshot descartado: el plan se modificó sin firmas")
    else:  # APROBADO, IMPLEMENTACION, SEGUIMIENTO
        nueva_version(db, plan, actor, motivo, request)
        abrio = True
    cambiar_estado(db, plan, S.EN_CONCERTACION, actor, request, motivo=motivo or "Edición del plan",
                   nueva_version=abrio)
    return abrio


# ----------------------------------------------------------------------------- bienestar: enviar
def enviar_a_estudiante(db: Session, plan: PlanMaarTea, actor: Usuario, request: Request | None = None) -> None:
    if plan.estado != S.BORRADOR:
        raise Conflict(f"Solo un plan en BORRADOR se envía al estudiante (estado actual: {plan.estado}).",
                       "TRANSICION_PLAN_INVALIDA")
    db.flush()
    n_aj = len(list(db.scalars(select(AjusteRazonable.id).where(AjusteRazonable.plan_id == plan.id))))
    n_es = len(list(db.scalars(select(EstrategiaDua.id).where(EstrategiaDua.plan_id == plan.id))))
    if n_aj + n_es == 0:
        raise Conflict("Agregue al menos un ajuste razonable o una estrategia DUA antes de enviar el plan al estudiante.",
                       "PLAN_VACIO")
    cambiar_estado(db, plan, S.EN_CONCERTACION, actor, request)
    plan.enviado_a_estudiante_at = utcnow()
    common.log_participacion(plan, actor, "ENVIO_A_ESTUDIANTE", "plan", plan.id)
    db.flush()


def razones_no_listo_para_validacion(db: Session, plan: PlanMaarTea) -> list[str]:
    db.flush()
    razones: list[str] = []
    ajustes = list(db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id)))
    n_es = len(list(db.scalars(select(EstrategiaDua.id).where(EstrategiaDua.plan_id == plan.id))))
    if not ajustes and n_es == 0:
        razones.append("El plan no tiene ajustes razonables ni estrategias DUA.")
    abiertas = {t.ajuste_id for t in tareas_abiertas(db, plan.id)}
    cerradas = {t.ajuste_id for t in db.scalars(select(TareaNegociacion).where(
        TareaNegociacion.plan_id == plan.id, TareaNegociacion.estado == EstadoTareaNegociacion.CERRADA))}
    for a in ajustes:
        if a.id in abiertas:
            razones.append(f"El ajuste «{a.nombre_ajuste}» tiene una negociación abierta.")
        elif a.aceptado_por_estudiante is True:
            continue
        elif a.respuesta_estudiante == Respuesta.OBJETADO and a.id in cerradas:
            continue  # desacuerdo resuelto por cierre (p. ej. decisión del Comité)
        elif a.respuesta_estudiante == Respuesta.MODIFICACION_PROPUESTA:
            razones.append(f"El estudiante propuso una modificación al ajuste «{a.nombre_ajuste}»: incorpórela o respóndala.")
        else:
            razones.append(f"El estudiante aún no ha aceptado el ajuste «{a.nombre_ajuste}».")
    return razones


def enviar_a_validacion(db: Session, plan: PlanMaarTea, actor: Usuario, request: Request | None = None) -> None:
    if plan.estado != S.EN_CONCERTACION:
        raise Conflict(f"Solo un plan en EN_CONCERTACION se envía a validación (estado actual: {plan.estado}).",
                       "TRANSICION_PLAN_INVALIDA")
    razones = razones_no_listo_para_validacion(db, plan)
    if razones:
        raise Conflict("El plan aún no está listo para validación: " + " ".join(razones), "PLAN_NO_LISTO_PARA_VALIDACION",
                       extra={"razones": razones})
    cambiar_estado(db, plan, S.PENDIENTE_VALIDACION, actor, request)
    plan.comentarios_validacion = None
    common.log_participacion(plan, actor, "ENVIO_A_VALIDACION", "plan", plan.id)
    est = common.estudiante_de(db, plan)
    # M10: «Plan listo para firma» al Coordinador (HU-25: recibe aviso cuando el plan espera su validación).
    common.notificar_plan(db, Evento.PLAN_LISTO_FIRMA, plan, common.coordinadores_usuarios(db, est.programa_id))


# ----------------------------------------------------------------------------- coordinador
def validar(db: Session, plan: PlanMaarTea, actor: Usuario, comentario: str | None, request: Request | None = None) -> None:
    if plan.estado != S.PENDIENTE_VALIDACION:
        raise Conflict(f"Solo un plan en PENDIENTE_VALIDACION se puede validar (estado actual: {plan.estado}).",
                       "TRANSICION_PLAN_INVALIDA")
    cambiar_estado(db, plan, S.PENDIENTE_FIRMAS, actor, request)
    plan.validado_por_id = actor.id
    plan.fecha_validacion = utcnow()
    plan.comentarios_validacion = comentario
    snap = sig.congelar_version(db, plan, actor)
    common.log_participacion(plan, actor, "VALIDO", "plan", plan.id, {"comentario": comentario, "hash": sig.hash_corto(snap.hash_snapshot)})
    destinatarios = [u for u in common.actores_del_plan(db, plan) if str(u.rol) in (Rol.ESTUDIANTE, Rol.BIENESTAR, Rol.COORDINADOR)]
    common.notificar_plan(db, Evento.PLAN_LISTO_FIRMA, plan, destinatarios)


def devolver(db: Session, plan: PlanMaarTea, actor: Usuario, comentarios: str, request: Request | None = None) -> None:
    if plan.estado not in (S.PENDIENTE_VALIDACION, S.PENDIENTE_FIRMAS):
        raise Conflict(f"Solo se puede devolver un plan en PENDIENTE_VALIDACION o PENDIENTE_FIRMAS (estado actual: {plan.estado}).",
                       "TRANSICION_PLAN_INVALIDA")
    preparar_edicion(db, plan, actor, f"Devuelto por el Coordinador: {comentarios[:200]}", request)
    plan.comentarios_validacion = comentarios
    common.log_participacion(plan, actor, "DEVOLVIO", "plan", plan.id, {"comentarios": comentarios})


# ----------------------------------------------------------------------------- estudiante
def respuesta_estudiante(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, actor: Usuario, respuesta: str,
                         comentario: str | None, request: Request | None = None) -> dict:
    """El estudiante acepta, propone una modificación (con texto) u objeta un ajuste. Objetar abre negociación."""
    if plan.estado not in (S.EN_CONCERTACION, S.EN_NEGOCIACION):
        raise Conflict(f"El plan no está en concertación (estado actual: {plan.estado}).", "PLAN_NO_ESTA_EN_CONCERTACION")
    if tareas_abiertas(db, plan.id, ajuste.id):
        raise Conflict("Este ajuste ya está en negociación. Responda desde la negociación abierta.", "AJUSTE_EN_NEGOCIACION")
    comentario = (comentario or "").strip() or None
    if respuesta in (Respuesta.MODIFICACION_PROPUESTA, Respuesta.OBJETADO) and (comentario is None or len(comentario) < 5):
        raise Unprocessable(
            "Cuéntenos con sus palabras qué cambiaría o por qué no está de acuerdo (mínimo 5 caracteres).",
            "COMENTARIO_REQUERIDO")
    ahora = utcnow()
    resultado: dict = {"ajuste_id": ajuste.id, "respuesta": respuesta, "negociacion": None}
    ajuste.respuesta_estudiante = respuesta
    ajuste.comentario_estudiante = comentario
    ajuste.aceptado_por_estudiante_at = ahora
    if respuesta == Respuesta.ACEPTADO:
        ajuste.aceptado_por_estudiante = True
        ajuste.modificacion_propuesta = None
        if ajuste.estado == EstadoAjuste.PROPUESTO:
            ajuste.estado = EstadoAjuste.ACORDADO
    elif respuesta == Respuesta.MODIFICACION_PROPUESTA:
        ajuste.aceptado_por_estudiante = None
        ajuste.modificacion_propuesta = comentario
    else:  # OBJETADO
        ajuste.aceptado_por_estudiante = False
        ajuste.modificacion_propuesta = None
        from app.services import negotiation

        tarea = negotiation.abrir(db, plan, ajuste, actor, comentario, request)
        resultado["negociacion"] = {"id": tarea.id, "estado": str(tarea.estado), "ciclo": tarea.ciclo}
    common.log_participacion(plan, actor, {"ACEPTADO": "ACEPTO", "MODIFICACION_PROPUESTA": "PROPUSO_MODIFICACION",
                                           "OBJETADO": "OBJETO"}[respuesta], "ajuste", ajuste.id, {"comentario": comentario})
    audit.log(db, actor, common.A_AJUSTE_RESPUESTA, "ajuste_razonable", ajuste.id,
              {"plan_id": plan.id, "respuesta": respuesta}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return resultado


# ----------------------------------------------------------------------------- docente
def aceptacion_docente(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, actor: Usuario, acepta: bool,
                       comentario: str | None, request: Request | None = None) -> None:
    if plan.estado not in ESTADOS_VIGENTES:
        raise Conflict("El docente acepta sus responsabilidades cuando el plan ya fue firmado y aprobado "
                       f"(estado actual: {plan.estado}).", "PLAN_NO_APROBADO")
    if ajuste.id not in docente_ajuste_ids(db, actor, plan.id):
        from app.core.errors import Forbidden

        raise Forbidden("Este ajuste no corresponde a sus asignaturas ni a sus responsabilidades.", "AJUSTE_NO_ES_SUYO")
    comentario = (comentario or "").strip() or None
    if not acepta and not comentario:
        raise Unprocessable("Si no puede asumir el ajuste, explique el motivo para que Bienestar lo revise.",
                            "COMENTARIO_REQUERIDO")
    ajuste.aceptado_por_responsable = bool(acepta)
    ajuste.aceptado_por_responsable_at = utcnow()
    ajuste.comentario_responsable = comentario
    common.log_participacion(plan, actor, "ACEPTO_RESPONSABILIDAD" if acepta else "DECLINO_RESPONSABILIDAD", "ajuste",
                             ajuste.id, {"comentario": comentario})
    audit.log(db, actor, common.A_AJUSTE_DOCENTE, "ajuste_razonable", ajuste.id,
              {"plan_id": plan.id, "acepta": bool(acepta)}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()


# ----------------------------------------------------------------------------- cierre del ciclo
def iniciar_implementacion(db: Session, plan: PlanMaarTea, actor: Usuario, request: Request | None = None) -> None:
    if plan.estado != S.APROBADO:
        raise Conflict(f"Solo un plan APROBADO pasa a implementación (estado actual: {plan.estado}).",
                       "TRANSICION_PLAN_INVALIDA")
    from app.models.apoyos import Apoyo

    db.flush()
    if db.scalar(select(Apoyo.id).where(Apoyo.plan_id == plan.id).limit(1)) is None:
        raise Conflict("Genere primero la matriz de responsabilidades (F7) del plan.", "MATRIZ_PENDIENTE")
    cambiar_estado(db, plan, S.IMPLEMENTACION, actor, request)
    for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id)):
        if a.estado in (EstadoAjuste.PROPUESTO, EstadoAjuste.ACORDADO):
            a.estado = EstadoAjuste.IMPLEMENTACION
    common.log_participacion(plan, actor, "INICIO_IMPLEMENTACION", "plan", plan.id)


def archivar(db: Session, plan: PlanMaarTea, actor: Usuario, motivo: str, request: Request | None = None) -> None:
    cambiar_estado(db, plan, S.ARCHIVADO, actor, request, motivo=motivo)
    common.log_participacion(plan, actor, "ARCHIVO", "plan", plan.id, {"motivo": motivo})


# ----------------------------------------------------------------------------- acciones disponibles (para la UI)
def acciones_disponibles(db: Session, plan: PlanMaarTea, user: Usuario) -> list[str]:
    rol = str(user.rol)
    est = plan.estado
    acc: list[str] = []
    firmadas = {str(f.rol_firmante) for f in sig.firmas_de(db, plan.id, plan.version, solo_vigentes=True)}
    if rol == Rol.BIENESTAR:
        if est not in (S.FINALIZADO, S.ARCHIVADO):
            acc.append("EDITAR")
        if est == S.BORRADOR:
            acc += ["ENVIAR_A_ESTUDIANTE", "ELIMINAR"]
        if est == S.EN_CONCERTACION and not razones_no_listo_para_validacion(db, plan):
            acc.append("ENVIAR_A_VALIDACION")
        if est in (S.APROBADO, S.IMPLEMENTACION, S.SEGUIMIENTO):
            acc.append("GENERAR_MATRIZ")
        if est == S.APROBADO:
            acc.append("INICIAR_IMPLEMENTACION")
        if est in (S.BORRADOR, S.EN_CONCERTACION, S.EN_NEGOCIACION, S.ESCALADO_COMITE, S.FINALIZADO):
            acc.append("ARCHIVAR")
        if est == S.PENDIENTE_FIRMAS and RolFirmante.BIENESTAR.value not in firmadas:
            acc.append("FIRMAR")
    elif rol == Rol.COORDINADOR:
        if est == S.PENDIENTE_VALIDACION:
            acc += ["VALIDAR", "DEVOLVER"]
        if est == S.PENDIENTE_FIRMAS:
            acc.append("DEVOLVER")
            if RolFirmante.COORDINADOR.value not in firmadas:
                acc.append("FIRMAR")
        if est in (S.APROBADO, S.IMPLEMENTACION, S.SEGUIMIENTO):
            acc.append("EDITAR_MATRIZ")
    elif rol == Rol.ESTUDIANTE:
        if est in (S.EN_CONCERTACION, S.EN_NEGOCIACION):
            acc.append("RESPONDER_AJUSTES")
        if est == S.PENDIENTE_FIRMAS and RolFirmante.ESTUDIANTE.value not in firmadas:
            acc.append("FIRMAR")
    elif rol == Rol.DOCENTE and est in ESTADOS_VIGENTES:
        acc.append("ACEPTAR_RESPONSABILIDAD")
    if rol in (Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE, Rol.FAMILIAR):
        acc.append("EXPORTAR")
    return acc


def hoy() -> date:
    return date.today()


def versiones_de(db: Session, plan: PlanMaarTea) -> list[PlanVersion]:
    db.flush()
    return list(db.scalars(select(PlanVersion).where(PlanVersion.plan_id == plan.id)
                           .execution_options(include_deleted=True).order_by(PlanVersion.version, PlanVersion.id)))
