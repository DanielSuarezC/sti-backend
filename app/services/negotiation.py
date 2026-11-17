"""Desacuerdo del estudiante / TareaNegociacion (RF-25, D12).

Ciclo (por ajuste objetado), máximo `max_ciclos_negociacion` (parámetro; por defecto 3, tope 3 por la restricción de BD):

    1. El estudiante objeta el ajuste           -> tarea ABIERTA   (ciclo 1, objeción registrada)
    2. Bienestar responde con una contrapropuesta -> tarea EN_CICLO
    3. El estudiante acepta                      -> ACORDADA  (fin)
       o no acepta y registra una nueva objeción -> ABIERTA con ciclo + 1 (vuelve al paso 2)
       o no acepta en el último ciclo            -> ESCALADA_COMITE + aviso al Comité de Inclusión
    4. Bienestar/Coordinador cierran con la decisión: ACORDADO, RETIRAR_AJUSTE o MANTENER_POR_COMITE (solo escaladas).

`historial` guarda por ciclo: {ciclo, objecion, propuesta, resolucion, fecha}.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.base import utcnow
from app.models.enums import (
    EstadoAjuste,
    EstadoEmail,
    EstadoPlanEnum,
    EstadoTareaNegociacion,
    TipoTareaNegociacion,
)
from app.models.plan import AjusteRazonable, PlanMaarTea, TareaNegociacion
from app.models.sistema import EmailOutbox
from app.models.usuarios import Usuario
from app.services import plan_common as common
from app.services.notifications import Evento, render
from app.services.params import get_param

T = EstadoTareaNegociacion
RESULTADOS_CIERRE = ("ACORDADO", "RETIRAR_AJUSTE", "MANTENER_POR_COMITE")


def max_ciclos(db: Session) -> int:
    try:
        n = int(get_param(db, "max_ciclos_negociacion", 3))
    except (TypeError, ValueError):
        n = 3
    return max(1, min(n, 3))  # CHECK ck_tarea_negociacion_ciclo (1..3)


def get_tarea(db: Session, tarea_id: int) -> TareaNegociacion:
    t = db.get(TareaNegociacion, tarea_id)
    if t is None or t.deleted_at is not None:
        raise NotFound("No encontramos la negociación indicada.", "NEGOCIACION_NO_ENCONTRADA")
    return t


def _hist(t: TareaNegociacion) -> list[dict]:
    return [dict(x) for x in (t.historial or [])]


def _set_hist(t: TareaNegociacion, hist: list[dict]) -> None:
    t.historial = hist  # reasignar: SQLAlchemy detecta el cambio del JSON


def _actual(hist: list[dict], ciclo: int) -> dict:
    for h in hist:
        if h.get("ciclo") == ciclo:
            return h
    h = {"ciclo": ciclo, "objecion": None, "propuesta": None, "resolucion": None, "fecha": utcnow().isoformat()}
    hist.append(h)
    return h


def siguiente_accion(t: TareaNegociacion) -> str | None:
    return {T.ABIERTA: "BIENESTAR_CONTRAPROPONE", T.EN_CICLO: "ESTUDIANTE_RESPONDE",
            T.ESCALADA_COMITE: "COMITE_DECIDE"}.get(T(str(t.estado)))


def _reabrir_plan(db: Session, plan: PlanMaarTea, actor: Usuario | None, request: Request | None) -> None:
    from app.services import plan_workflow as wf

    if not wf.tareas_abiertas(db, plan.id) and plan.estado in (EstadoPlanEnum.EN_NEGOCIACION, EstadoPlanEnum.ESCALADO_COMITE):
        wf.cambiar_estado(db, plan, EstadoPlanEnum.EN_CONCERTACION, actor, request, motivo="Negociación resuelta")


def abrir(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, actor: Usuario, objecion: str,
          request: Request | None = None) -> TareaNegociacion:
    """Ciclo 1: el estudiante objeta un ajuste. El plan pasa a EN_NEGOCIACION."""
    from app.services import plan_workflow as wf

    t = TareaNegociacion(
        plan_id=plan.id, ajuste_id=ajuste.id, tipo=TipoTareaNegociacion.OBJECION_AJUSTE, estado=T.ABIERTA, ciclo=1,
        objecion_estudiante=objecion, creada_por_id=actor.id, asignada_a_id=plan.elaborado_por_id,
        historial=[{"ciclo": 1, "objecion": objecion, "propuesta": None, "resolucion": None,
                    "fecha": utcnow().isoformat()}],
    )
    db.add(t)
    db.flush()
    if plan.estado == EstadoPlanEnum.EN_CONCERTACION:
        wf.cambiar_estado(db, plan, EstadoPlanEnum.EN_NEGOCIACION, actor, request, motivo="Objeción del estudiante")
    plan.ciclos_negociacion = max(plan.ciclos_negociacion or 0, 1)
    audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id,
              {"evento": "ABIERTA", "plan_id": plan.id, "ajuste_id": ajuste.id, "ciclo": 1}, request=request,
              estudiante_id=plan.estudiante_id)
    return t


def contrapropuesta(db: Session, t: TareaNegociacion, actor: Usuario, propuesta: str, cambios_ajuste: dict | None,
                    request: Request | None = None) -> TareaNegociacion:
    """Bienestar responde a la objeción (opcionalmente modificando el ajuste en el mismo acto)."""
    if t.estado != T.ABIERTA:
        raise Conflict(f"La contrapropuesta se registra cuando la negociación espera a Bienestar (estado actual: {t.estado}).",
                       "NEGOCIACION_ESTADO_INVALIDO")
    plan = common.get_plan(db, t.plan_id)
    if cambios_ajuste:
        from app.services import plan_builder

        ajuste = common.get_ajuste(db, plan, t.ajuste_id)
        plan_builder.actualizar_ajuste(db, plan, ajuste, actor, cambios_ajuste, request, via_negociacion=True)
    hist = _hist(t)
    _actual(hist, t.ciclo)["propuesta"] = propuesta
    _set_hist(t, hist)
    t.propuesta_bienestar = propuesta
    t.estado = T.EN_CICLO
    common.log_participacion(plan, actor, "CONTRAPROPUSO", "ajuste", t.ajuste_id, {"ciclo": t.ciclo, "negociacion_id": t.id})
    audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id,
              {"evento": "CONTRAPROPUESTA", "ciclo": t.ciclo}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return t


def responder(db: Session, t: TareaNegociacion, actor: Usuario, acepta: bool, comentario: str | None,
              request: Request | None = None) -> TareaNegociacion:
    """El estudiante acepta la contrapropuesta, o la rechaza con una nueva objeción (siguiente ciclo o escalamiento)."""
    if t.estado != T.EN_CICLO:
        raise Conflict(f"El estudiante responde cuando Bienestar ya hizo su contrapropuesta (estado actual: {t.estado}).",
                       "NEGOCIACION_ESTADO_INVALIDO")
    plan = common.get_plan(db, t.plan_id)
    ajuste = common.get_ajuste(db, plan, t.ajuste_id)
    hist = _hist(t)
    h = _actual(hist, t.ciclo)
    ahora = utcnow()
    if acepta:
        h["resolucion"] = "ACORDADO"
        h["respuesta_estudiante"] = comentario
        _set_hist(t, hist)
        t.estado = T.ACORDADA
        t.resolucion = f"Acuerdo en el ciclo {t.ciclo}."
        t.resuelta_at = ahora
        ajuste.respuesta_estudiante = "ACEPTADO"
        ajuste.aceptado_por_estudiante = True
        ajuste.aceptado_por_estudiante_at = ahora
        ajuste.comentario_estudiante = comentario
        if ajuste.estado == EstadoAjuste.PROPUESTO:
            ajuste.estado = EstadoAjuste.ACORDADO
        common.log_participacion(plan, actor, "ACEPTO", "ajuste", ajuste.id, {"negociacion_id": t.id, "ciclo": t.ciclo})
        audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id, {"evento": "ACORDADA", "ciclo": t.ciclo},
                  request=request, estudiante_id=plan.estudiante_id)
        db.flush()
        _reabrir_plan(db, plan, actor, request)
        return t
    comentario = (comentario or "").strip()
    if len(comentario) < 5:
        raise Unprocessable("Si no acepta la contrapropuesta, cuéntenos por qué (mínimo 5 caracteres).", "COMENTARIO_REQUERIDO")
    h["resolucion"] = "SIN_ACUERDO"
    h["respuesta_estudiante"] = comentario
    limite = max_ciclos(db)
    if t.ciclo < limite:
        t.ciclo += 1
        hist.append({"ciclo": t.ciclo, "objecion": comentario, "propuesta": None, "resolucion": None,
                     "fecha": ahora.isoformat()})
        _set_hist(t, hist)
        t.objecion_estudiante = comentario
        t.propuesta_bienestar = None
        t.estado = T.ABIERTA
        plan.ciclos_negociacion = max(plan.ciclos_negociacion or 0, t.ciclo)
        common.log_participacion(plan, actor, "OBJETO", "ajuste", ajuste.id, {"negociacion_id": t.id, "ciclo": t.ciclo})
        audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id,
                  {"evento": "NUEVO_CICLO", "ciclo": t.ciclo}, request=request, estudiante_id=plan.estudiante_id)
        db.flush()
        return t
    _set_hist(t, hist)
    t.estado = T.ESCALADA_COMITE
    t.escalada_at = ahora
    t.resolucion = f"Sin acuerdo tras {limite} ciclos: escalado al Comité de Inclusión."
    plan.ciclos_negociacion = max(plan.ciclos_negociacion or 0, limite)
    from app.services import plan_workflow as wf

    if plan.estado == EstadoPlanEnum.EN_NEGOCIACION:
        wf.cambiar_estado(db, plan, EstadoPlanEnum.ESCALADO_COMITE, actor, request, motivo="Sin acuerdo tras los ciclos")
    common.log_participacion(plan, actor, "ESCALO_A_COMITE", "ajuste", ajuste.id, {"negociacion_id": t.id, "ciclos": limite})
    audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id,
              {"evento": "ESCALADA_COMITE", "ciclos": limite}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    notificar_escalamiento(db, plan, ajuste, t, limite)
    return t


def emails_comite(db: Session) -> list[str]:
    raw = get_param(db, "comite_inclusion_emails", None)
    if raw is None:
        raw = get_param(db, "comite_inclusion_email", "")
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace(";", ",").split(",")]
    return [str(e).strip() for e in (raw or []) if str(e).strip()]


def notificar_escalamiento(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, t: TareaNegociacion, ciclos: int) -> None:
    """«TareaNegociacion escalada a Comité»: todos los actores del plan + correos del Comité de Inclusión (parámetro)."""
    payload = {"ajuste": ajuste.nombre_ajuste, "ciclos": ciclos, "negociacion_id": t.id}
    common.notificar_plan(db, Evento.NEGOCIACION_ESCALADA_COMITE, plan, common.actores_del_plan(db, plan), payload)
    try:
        from app.core.config import get_settings
        from app.services import email as email_service

        for correo in emails_comite(db):
            titulo, asunto, cuerpo, _ = render(Evento.NEGOCIACION_ESCALADA_COMITE,
                                              {**payload, "enlace": f"/bienestar/negociaciones/{t.id}"})
            row = EmailOutbox(usuario_id=None, destinatario_email=correo, asunto=asunto, cuerpo_texto=cuerpo,
                              evento=Evento.NEGOCIACION_ESCALADA_COMITE.value, estado=EstadoEmail.PENDIENTE)
            db.add(row)
            db.flush()
            if not get_settings().smtp_configured:
                email_service.deliver(row)
            else:
                from app.services.notifications import _schedule_after_commit

                _schedule_after_commit(db)
    except Exception:  # noqa: BLE001
        common.logger.exception("No se pudo notificar al Comité de Inclusión")


def cerrar(db: Session, t: TareaNegociacion, actor: Usuario, resultado: str, resolucion: str,
           request: Request | None = None) -> TareaNegociacion:
    """Cierre por Bienestar/Coordinador. ACORDADO y RETIRAR_AJUSTE: cualquier momento. MANTENER_POR_COMITE: solo escaladas."""
    if resultado not in RESULTADOS_CIERRE:
        raise Unprocessable(f"Resultado no válido. Use: {', '.join(RESULTADOS_CIERRE)}.", "RESULTADO_INVALIDO")
    if t.estado not in (T.ABIERTA, T.EN_CICLO, T.ESCALADA_COMITE):
        raise Conflict(f"La negociación ya está cerrada (estado: {t.estado}).", "NEGOCIACION_ESTADO_INVALIDO")
    if resultado == "MANTENER_POR_COMITE" and t.estado != T.ESCALADA_COMITE:
        raise Conflict("Mantener un ajuste por decisión del Comité solo aplica a negociaciones escaladas.",
                       "NEGOCIACION_NO_ESCALADA")
    plan = common.get_plan(db, t.plan_id)
    ajuste = common.get_ajuste(db, plan, t.ajuste_id)
    ahora = utcnow()
    hist = _hist(t)
    _actual(hist, t.ciclo)["resolucion"] = resultado
    _set_hist(t, hist)
    if resultado == "RETIRAR_AJUSTE":
        from app.services import plan_builder

        plan_builder.eliminar_ajuste(db, plan, ajuste, actor, resolucion, request)  # cierra la tarea (cerrar_por_retiro)
        t.resolucion = resolucion
        return t
    t.resolucion = resolucion
    t.resuelta_at = ahora
    if resultado == "ACORDADO":
        t.estado = T.ACORDADA
        ajuste.respuesta_estudiante = "ACEPTADO"
        ajuste.aceptado_por_estudiante = True
        ajuste.aceptado_por_estudiante_at = ahora
        if ajuste.estado == EstadoAjuste.PROPUESTO:
            ajuste.estado = EstadoAjuste.ACORDADO
    else:
        t.estado = T.CERRADA  # el Comité mantiene el ajuste; la objeción del estudiante queda registrada
    common.log_participacion(plan, actor, "CERRO_NEGOCIACION", "ajuste", ajuste.id, {"resultado": resultado, "negociacion_id": t.id})
    audit.log(db, actor, common.A_NEGOCIACION, "tarea_negociacion", t.id, {"evento": "CERRADA", "resultado": resultado},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    _reabrir_plan(db, plan, actor, request)
    return t


def cerrar_por_retiro(db: Session, plan: PlanMaarTea, t: TareaNegociacion, actor: Usuario, motivo: str) -> None:
    """El ajuste se retiró del plan: la negociación se cierra."""
    t.estado = T.CERRADA
    t.resolucion = f"Ajuste retirado del plan: {motivo}"
    t.resuelta_at = utcnow()
    db.flush()
    _reabrir_plan(db, plan, actor, None)


def serializar(db: Session, t: TareaNegociacion, plan: PlanMaarTea | None = None) -> dict:
    plan = plan or db.get(PlanMaarTea, t.plan_id)
    ajuste = db.get(AjusteRazonable, t.ajuste_id) if t.ajuste_id else None
    return {
        "id": t.id, "plan_id": t.plan_id, "estudiante_id": plan.estudiante_id if plan else None,
        "ajuste": ({"id": ajuste.id, "nombre_ajuste": ajuste.nombre_ajuste, "tipo_ajuste": str(ajuste.tipo_ajuste)}
                   if ajuste else None),
        "tipo": str(t.tipo), "estado": str(t.estado), "ciclo": t.ciclo, "max_ciclos": max_ciclos(db),
        "objecion_estudiante": t.objecion_estudiante, "propuesta_bienestar": t.propuesta_bienestar,
        "resolucion": t.resolucion, "historial": t.historial or [], "siguiente_accion": siguiente_accion(t),
        "creada_por": common.ref_usuario(db, t.creada_por_id), "asignada_a": common.ref_usuario(db, t.asignada_a_id),
        "escalada_at": t.escalada_at.isoformat() if t.escalada_at else None,
        "resuelta_at": t.resuelta_at.isoformat() if t.resuelta_at else None, "created_at": t.created_at.isoformat(),
    }


def tareas_del_plan(db: Session, plan_id: int) -> list[TareaNegociacion]:
    db.flush()
    return list(db.scalars(select(TareaNegociacion).where(TareaNegociacion.plan_id == plan_id).order_by(TareaNegociacion.id)))
