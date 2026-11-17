"""Evaluacion de efectividad F9 (M7): borrador consolidado de C1+C2+C3, decisiones por ajuste, valoracion de las 9
dimensiones, cierre (plan -> FINALIZADO) y alimentacion del CBR.

# OWNER: slice C2
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.base import utcnow
from app.models.enums import DimensionResultado, EstadoDecision, EstadoPlanEnum
from app.models.evaluacion import DecisionPlan, EvaluacionPlan
from app.models.plan import EstadoPlan, PlanMaarTea
from app.models.seguimiento import EvidenciaEfectividad
from app.models.usuarios import Estudiante, Usuario
from app.services import seguimiento as seg
from app.services import semaforo as sem
from app.services.cbr_feedback import alimentar_cbr
from app.services.plan_states import assert_transition

DIMENSIONES = [d.value for d in DimensionResultado]
CORTES = sem.ORDEN_CORTES


def get_evaluacion(db: Session, plan_id: int) -> EvaluacionPlan | None:
    return db.scalar(select(EvaluacionPlan).where(EvaluacionPlan.plan_id == plan_id).order_by(EvaluacionPlan.id.desc()))


def exigir_evaluacion(db: Session, plan_id: int) -> EvaluacionPlan:
    ev = get_evaluacion(db, plan_id)
    if ev is None:
        raise NotFound("Este plan todavía no tiene evaluación (F9). Cree el borrador primero.", "EVALUACION_NO_ENCONTRADA")
    return ev


def _decision_sugerida(semaforos: list[str | None]) -> tuple[str | None, str]:
    v = [s for s in semaforos if s]
    if not v:
        return None, "Sin valoraciones de semáforo."
    ult = v[-1]
    if ult == "VERDE":
        return "MANTENER", "El último semáforo es VERDE: el ajuste funciona."
    if ult == "AMARILLO":
        return "MODIFICAR", "El último semáforo es AMARILLO: efectividad parcial; conviene afinar el ajuste."
    if len(v) >= 2 and v[-2] == "ROJO":
        return "RETIRAR", "ROJO en cortes consecutivos: el ajuste no funciona; considere retirarlo y reemplazarlo."
    return "MODIFICAR", "El último semáforo es ROJO: el ajuste debe rediseñarse."


def _nivel(pct: float | None) -> str | None:
    return None if pct is None else "ALTA" if pct >= 80 else "MEDIA" if pct >= 50 else "BAJA"


def tendencia(db: Session, plan: PlanMaarTea, matriz: dict | None = None) -> dict:
    """Datos para el grafico C1->C2->C3: valor 0=VERDE, 1=AMARILLO, 2=ROJO, null = sin valorar."""
    m = matriz or sem.construir_matriz(db, plan)
    return {
        "cortes": list(CORTES), "escala": {"VERDE": 0, "AMARILLO": 1, "ROJO": 2},
        "series": [{"ajuste_id": f["ajuste_id"], "nombre_ajuste": f["nombre_ajuste"], "tendencia": f["tendencia"],
                    "semaforos": [f["cortes"][c]["semaforo"] if f["cortes"][c] else None for c in CORTES],
                    "valores": [sem.rank(f["cortes"][c]["semaforo"]) if f["cortes"][c] else None for c in CORTES]}
                   for f in m["ajustes"]],
        "agregado": [{"corte": c, **{k: m["resumen"]["por_corte"][c][k] for k in ("VERDE", "AMARILLO", "ROJO", "SIN_VALORAR", "porcentaje_verde")}}
                     for c in CORTES],
    }


def sintesis(db: Session, plan: PlanMaarTea) -> dict:
    """Consolidacion automatica de los registros de seguimiento por ajuste + indicadores D6/D8."""
    m = sem.construir_matriz(db, plan)
    segs = seg.seguimientos_por_corte(db, plan.id)
    ajustes = []
    for f in m["ajustes"]:
        evol = []
        for c in CORTES:
            r = f["cortes"][c]
            if r:
                evol.append({"corte": c, "semaforo": r["semaforo"], "implementado": r["implementado"],
                             "frecuencia_implementacion": r["frecuencia_implementacion"],
                             "resultado_observado": r["resultado_observado"], "percepcion": r["percepcion_estudiante"],
                             "comentario_estudiante": r["comentario_estudiante"], "estado_seguimiento": r["estado_seguimiento"]})
        impl = [e["implementado"] for e in evol if e["implementado"] is not None]
        dec, motivo = _decision_sugerida([e["semaforo"] for e in evol])
        ajustes.append({
            "ajuste_id": f["ajuste_id"], "nombre_ajuste": f["nombre_ajuste"], "tipo_ajuste": f["tipo_ajuste"],
            "evolucion": evol, "tendencia": f["tendencia"], "semaforo_final": f["semaforo_actual"],
            "tasa_implementacion": round(100 * sum(1 for x in impl if x) / len(impl), 1) if impl else None,
            "decision_sugerida": dec, "motivo_sugerencia": motivo,
        })
    evidencias, por_dim, barreras = [], {d: [] for d in DIMENSIONES}, []
    for c in CORTES:
        s = segs.get(c)
        if s is None:
            continue
        barreras.extend({**b, "corte": c} for b in (s.barreras_emergentes or []))
        for e in db.scalars(select(EvidenciaEfectividad).where(EvidenciaEfectividad.seguimiento_id == s.id)):
            ev = seg._evidencia(db, e)
            evidencias.append({"corte": c, **ev})
            for r in ev["resultados"]:
                if r["porcentaje_cumplimiento"] is not None:
                    por_dim[r["dimension_resultado"]].append(r["porcentaje_cumplimiento"])
    dims = {}
    for d in DIMENSIONES:
        vals = por_dim[d]
        prom = round(sum(vals) / len(vals), 1) if vals else None
        dims[d] = {"promedio_cumplimiento": prom, "n_indicadores": len(vals), "nivel_sugerido": _nivel(prom)}
    d6, d8 = seg.tasa_implementacion(db, plan.id, "C2"), seg.porcentaje_verde(db, plan.id)
    sug = "ALTA" if (d8["valor"] or 0) >= 80 else "MEDIA" if (d8["valor"] or 0) >= 50 else "BAJA"
    return {
        "plan_id": plan.id, "semestre": plan.semestre_academico,
        "cortes": [{"corte": c, "estado": ("CERRADO" if segs[c].cerrado else "ABIERTO") if c in segs else "SIN_ABRIR",
                    **{k: m["resumen"]["por_corte"][c][k] for k in ("VERDE", "AMARILLO", "ROJO", "SIN_VALORAR", "porcentaje_verde")}}
                   for c in CORTES],
        "ajustes": ajustes, "indicadores": {"D6": d6, "D8": d8}, "evidencias": evidencias, "dimensiones": dims,
        "barreras_emergentes": barreras, "efectividad_general_sugerida": sug,
    }


# ============================================================================ crear / patch
def crear_borrador(db: Session, plan: PlanMaarTea, est: Estudiante, actor: Usuario, request=None) -> EvaluacionPlan:
    if plan.estado not in seg.ESTADOS_PLAN_SEGUIMIENTO:
        raise Conflict(f"La evaluación F9 se crea con el plan en IMPLEMENTACION o SEGUIMIENTO (está en {plan.estado}).",
                       "PLAN_NO_EN_SEGUIMIENTO")
    if get_evaluacion(db, plan.id) is not None:
        raise Conflict("Este plan ya tiene una evaluación F9. Consúltela o edítela en lugar de crear otra.", "EVALUACION_YA_EXISTE")
    if not seg.seguimientos_por_corte(db, plan.id):
        raise Conflict("Todavía no hay seguimiento (F8) registrado: no hay nada que consolidar.", "SIN_SEGUIMIENTO")
    s = sintesis(db, plan)
    ev = EvaluacionPlan(
        plan_id=plan.id, fecha_evaluacion=date.today(), evaluador_id=actor.id, periodo_evaluacion=plan.semestre_academico,
        efectividad_general=s["efectividad_general_sugerida"], estado="BORRADOR", sintesis=s,
        evidencias_resumidas=_resumen_texto(s),
    )
    db.add(ev)
    db.flush()
    audit.log(db, actor, "EVALUACION_CREADA", "evaluacion_plan", ev.id, {"plan_id": plan.id}, request=request, estudiante_id=est.id)
    return ev


def _resumen_texto(s: dict) -> str:
    partes = [f"{c['corte']}: {c['VERDE']} verde, {c['AMARILLO']} amarillo, {c['ROJO']} rojo ({c['estado'].lower()})" for c in s["cortes"]]
    d6, d8 = s["indicadores"]["D6"], s["indicadores"]["D8"]
    return ("Consolidado de seguimiento. " + "; ".join(partes)
            + f". Implementación al C2: {d6['valor']} % (meta {d6['meta']} %). Ajustes en verde: {d8['valor']} % (meta {d8['meta']} %).")


def _validar_decisiones(db: Session, plan: PlanMaarTea, decisiones: list) -> dict[int, str]:
    activos = {a.id: a for a in sem.ajustes_activos(db, plan.id)}
    ultimo = {a.id: (str(a.semaforo_actual) if a.semaforo_actual else None) for a in activos.values()}
    vistos: set[int] = set()
    for d in decisiones:
        t = str(d.tipo_decision)
        if t == "CREAR_NUEVO":
            if d.ajuste_id is not None:
                raise Unprocessable("CREAR_NUEVO no se asocia a un ajuste existente: deje ajuste_id vacío.", "DECISION_INVALIDA")
            if not (d.descripcion_decision or "").strip():
                raise Unprocessable("Para CREAR_NUEVO describa el ajuste nuevo (descripcion_decision).", "DESCRIPCION_REQUERIDA")
            continue
        if d.ajuste_id is None:
            raise Unprocessable(f"La decisión {t} necesita el ajuste (ajuste_id).", "AJUSTE_REQUERIDO")
        if d.ajuste_id not in activos:
            raise NotFound("Uno de los ajustes no pertenece a este plan.", "AJUSTE_NO_ENCONTRADO")
        if d.ajuste_id in vistos:
            raise Unprocessable("Hay dos decisiones para el mismo ajuste.", "DECISION_DUPLICADA")
        vistos.add(d.ajuste_id)
        if t == "MANTENER" and ultimo.get(d.ajuste_id) == "ROJO":
            raise Unprocessable(
                f"El ajuste «{activos[d.ajuste_id].nombre_ajuste}» terminó en ROJO: no puede mantenerse tal cual. "
                "Elija MODIFICAR o RETIRAR.", "DECISION_INCOMPATIBLE_ROJO")
    return {a: n.nombre_ajuste for a, n in activos.items()}


def patch(db: Session, plan: PlanMaarTea, est: Estudiante, ev: EvaluacionPlan, datos: dict, decisiones: list | None,
          valoracion: dict | None, actor: Usuario, request=None) -> EvaluacionPlan:
    if ev.estado == "CERRADA":
        raise Conflict("La evaluación ya está cerrada y no se puede modificar.", "EVALUACION_CERRADA")
    if decisiones:
        nombres = _validar_decisiones(db, plan, decisiones)
        existentes = list(db.scalars(select(DecisionPlan).where(DecisionPlan.evaluacion_id == ev.id)))
        for d in decisiones:
            if d.ajuste_id is not None:
                fila = next((x for x in existentes if x.elemento_id == d.ajuste_id and str(x.elemento_afectado) == "AJUSTE"), None)
                desc = d.descripcion_decision or f"{d.tipo_decision} el ajuste «{nombres[d.ajuste_id]}»"
            else:
                fila = next((x for x in existentes if x.elemento_id is None and x.descripcion_decision == d.descripcion_decision), None)
                desc = d.descripcion_decision
            if fila is None:
                fila = DecisionPlan(evaluacion_id=ev.id, elemento_afectado="AJUSTE", elemento_id=d.ajuste_id,
                                    responsable_decision_id=actor.id, descripcion_decision=desc, tipo_decision=d.tipo_decision)
                db.add(fila)
            fila.tipo_decision, fila.descripcion_decision = d.tipo_decision, desc
            fila.justificacion_decision, fila.lecciones_aprendidas = d.justificacion, d.lecciones_aprendidas
            fila.fecha_implementacion_decision, fila.responsable_decision_id = d.fecha_implementacion_decision, actor.id
    if valoracion is not None:
        actual = dict(ev.valoracion_dimensiones or {})
        for dim, v in valoracion.items():
            actual[str(dim)] = {"nivel": str(v.nivel), "comentario": v.comentario}
        ev.valoracion_dimensiones = actual
    for k, v in datos.items():
        setattr(ev, k, v)
    ev.evaluador_id = ev.evaluador_id or actor.id
    audit.log(db, actor, "EVALUACION_ACTUALIZADA", "evaluacion_plan", ev.id, {"campos": sorted(datos), "decisiones": len(decisiones or [])},
              request=request, estudiante_id=est.id)
    db.flush()
    return ev


def eliminar_decision(db: Session, ev: EvaluacionPlan, decision_id: int, actor: Usuario, est: Estudiante, request=None) -> None:
    if ev.estado == "CERRADA":
        raise Conflict("La evaluación ya está cerrada y no se puede modificar.", "EVALUACION_CERRADA")
    d = db.get(DecisionPlan, decision_id)
    if d is None or d.evaluacion_id != ev.id:
        raise NotFound("No encontramos esa decisión.", "DECISION_NO_ENCONTRADA")
    seg.soft_delete(db, d, actor, "Decisión retirada del borrador F9", est.id, request)


# ============================================================================ estado de cierre / serializar
def decisiones_de(db: Session, ev: EvaluacionPlan) -> list[DecisionPlan]:
    return list(db.scalars(select(DecisionPlan).where(DecisionPlan.evaluacion_id == ev.id).order_by(DecisionPlan.id)))


def bloqueos_cierre(db: Session, plan: PlanMaarTea, ev: EvaluacionPlan) -> list[dict]:
    out = []
    c3 = seg.seguimientos_por_corte(db, plan.id).get("C3")
    if c3 is None or not c3.cerrado:
        out.append({"code": "C3_NO_CERRADO", "detail": "Cierre primero el seguimiento del corte C3."})
    con_decision = {d.elemento_id for d in decisiones_de(db, ev) if str(d.elemento_afectado) == "AJUSTE" and d.elemento_id}
    faltan = [a for a in sem.ajustes_activos(db, plan.id) if a.id not in con_decision]
    if faltan:
        out.append({"code": "DECISIONES_INCOMPLETAS", "detail": "Falta la decisión de: " + ", ".join(f"«{a.nombre_ajuste}»" for a in faltan),
                    "ajuste_ids": [a.id for a in faltan]})
    val = ev.valoracion_dimensiones or {}
    sin = [d for d in DIMENSIONES if d not in val]
    if sin:
        out.append({"code": "VALORACION_INCOMPLETA", "detail": "Falta valorar las dimensiones: " + ", ".join(sin).lower(), "dimensiones": sin})
    if plan.estado != EstadoPlanEnum.SEGUIMIENTO:
        out.append({"code": "PLAN_NO_EN_SEGUIMIENTO", "detail": f"El plan debe estar en SEGUIMIENTO (está en {plan.estado})."})
    return out


def serializar(db: Session, plan: PlanMaarTea, ev: EvaluacionPlan) -> dict:
    cerrada = ev.estado == "CERRADA"
    s = ev.sintesis if cerrada and ev.sintesis else sintesis(db, plan)
    bl = [] if cerrada else bloqueos_cierre(db, plan, ev)
    return {
        "id": ev.id, "plan_id": plan.id, "estado": ev.estado, "fecha_evaluacion": ev.fecha_evaluacion.isoformat(),
        "evaluador_id": ev.evaluador_id, "periodo_evaluacion": ev.periodo_evaluacion,
        "efectividad_general": str(ev.efectividad_general), "evidencias_resumidas": ev.evidencias_resumidas,
        "apoyos_efectivos": ev.apoyos_efectivos, "apoyos_requieren_ajuste": ev.apoyos_requieren_ajuste,
        "apoyos_a_discontinuar": ev.apoyos_a_discontinuar, "nuevas_barreras_identificadas": ev.nuevas_barreras_identificadas,
        "fortalezas_emergentes": ev.fortalezas_emergentes, "cambios_contexto": ev.cambios_contexto,
        "recomendaciones": ev.recomendaciones, "lecciones_aprendidas": ev.lecciones_aprendidas,
        "alimento_cbr": ev.alimento_cbr, "cerrada_at": ev.cerrada_at.isoformat() if ev.cerrada_at else None,
        "valoracion_dimensiones": ev.valoracion_dimensiones or {},
        "decisiones": [{"id": d.id, "ajuste_id": d.elemento_id, "tipo_decision": str(d.tipo_decision),
                        "elemento_afectado": str(d.elemento_afectado), "descripcion_decision": d.descripcion_decision,
                        "justificacion": d.justificacion_decision, "lecciones_aprendidas": d.lecciones_aprendidas,
                        "estado_decision": str(d.estado_decision),
                        "fecha_implementacion_decision": d.fecha_implementacion_decision.isoformat() if d.fecha_implementacion_decision else None}
                       for d in decisiones_de(db, ev)],
        "sintesis": s, "tendencia": tendencia(db, plan), "puede_cerrar": not bl and not cerrada, "bloqueos_cierre": bl,
    }


# ============================================================================ cierre
def cerrar(db: Session, plan: PlanMaarTea, est: Estudiante, ev: EvaluacionPlan, actor: Usuario, request=None) -> dict:
    if ev.estado == "CERRADA":
        raise Conflict("La evaluación ya está cerrada.", "EVALUACION_CERRADA")
    bl = bloqueos_cierre(db, plan, ev)
    if bl:
        primero = bl[0]
        raise Conflict(primero["detail"], primero["code"], extra={"bloqueos": bl})
    assert_transition(plan.estado, EstadoPlanEnum.FINALIZADO)
    decisiones = decisiones_de(db, ev)
    por_tipo: dict[str, list[str]] = {"MANTENER": [], "MODIFICAR": [], "RETIRAR": []}
    nombres = {a.id: a for a in sem.ajustes_activos(db, plan.id)}
    final = db.scalar(select(EstadoPlan.id).where(EstadoPlan.nombre_estado == "FINALIZADO"))
    for d in decisiones:
        d.estado_decision = EstadoDecision.ACORDADA
        d.estado_plan_resultante_id = final
        if d.elemento_id in nombres and str(d.tipo_decision) in por_tipo:
            por_tipo[str(d.tipo_decision)].append(nombres[d.elemento_id].nombre_ajuste)
    ev.apoyos_efectivos = "; ".join(por_tipo["MANTENER"]) or None
    ev.apoyos_requieren_ajuste = "; ".join(por_tipo["MODIFICAR"]) or None
    ev.apoyos_a_discontinuar = "; ".join(por_tipo["RETIRAR"]) or None
    s = sintesis(db, plan)
    verdes = []
    for a in nombres.values():
        if a.semaforo_actual is not None and str(a.semaforo_actual) == "VERDE":
            percs = [r.percepcion_estudiante for r, _ in sem.registros_del_plan(db, plan.id)
                     if r.ajuste_id == a.id and r.percepcion_estudiante is not None]
            verdes.append((a, str(percs[-1]) if percs else None))
    cbr = alimentar_cbr(db, plan, verdes)
    ev.sintesis, ev.estado, ev.cerrada_at, ev.alimento_cbr = s, "CERRADA", utcnow(), True
    ev.evidencias_resumidas = _resumen_texto(s)
    plan.estado = EstadoPlanEnum.FINALIZADO
    db.flush()
    audit.log(db, actor, "EVALUACION_CERRADA", "evaluacion_plan", ev.id, {"plan_id": plan.id, "cbr": cbr},
              request=request, estudiante_id=est.id)
    return {"cbr": cbr, "plan_estado": str(plan.estado)}


__all__: list[Any] = ["crear_borrador", "cerrar", "patch", "serializar", "sintesis", "tendencia", "exigir_evaluacion"]
