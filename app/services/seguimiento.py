"""Seguimiento F8 por cortes (M6): calendario, apertura/cierre de cortes, registro por ajuste, percepcion del estudiante,
evidencias, barreras emergentes y funciones que consume `run_daily_jobs` (slice A).

# OWNER: slice C2

Funciones publicas para otros slices (firmas estables)::

    cortes_proximos(db, hoy, dias=(7, 1)) -> list[dict]
        [{"corte": "C1", "fecha_corte": date, "dias_restantes": 7, "semestre": "2026-II", "calendario_id": 3,
          "programa_id": None}]            # cortes de calendarios ACTIVOS que caen dentro de `dias` dias
    pendientes_de_corte(db, corte, *, calendario_id=None) -> list[dict]
        [{"plan_id", "estudiante_id", "estudiante_usuario_id", "bienestar_usuario_id", "docente_usuario_ids": [..],
          "ajuste_ids": [..], "estado_corte": "SIN_ABRIR" | "ABIERTO", "calendario_id", "fecha_corte", "semestre"}]
        # planes en IMPLEMENTACION/SEGUIMIENTO cuyo F8 del corte aun no esta cerrado: a quienes recordar
    tasa_implementacion(db, plan_id, hasta="C2") -> dict   # indicador D6 (>= 80 % al C2)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.academico import CalendarioAcademico
from app.models.base import utcnow
from app.models.enums import EstadoPlanEnum, Rol, TipoAjuste
from app.models.mapa import BarreraIdentificada, BarreraSocial
from app.models.plan import AjusteRazonable, PlanMaarTea
from app.models.seguimiento import (
    EvidenciaEfectividad,
    RegistroSeguimiento,
    RegistroSeguimientoAjuste,
    ResultadoIndicador,
    Seguimiento,
)
from app.models.usuarios import Estudiante, Usuario
from app.services import semaforo as sem
from app.services.plan_states import assert_transition
from app.services.ruta import ruta_front

CORTES = sem.ORDEN_CORTES
ESTADOS_PLAN_SEGUIMIENTO = (EstadoPlanEnum.IMPLEMENTACION, EstadoPlanEnum.SEGUIMIENTO)
META_PORCENTAJE = 80  # D6 (al C2) y D8 (al C3)


# ============================================================================ calendario y plan
def get_plan_or_404(db: Session, plan_id: int) -> PlanMaarTea:
    plan = db.get(PlanMaarTea, plan_id)
    if plan is None:
        raise NotFound("No encontramos el Plan MAAR-TEA indicado.", "PLAN_NO_ENCONTRADO")
    return plan


def calendario_para(db: Session, plan: PlanMaarTea, est: Estudiante) -> CalendarioAcademico:
    """Calendario ACTIVO aplicable al plan (preferencia: mismo semestre y del programa). 409 claro si no hay ninguno."""
    cals = [
        c for c in db.scalars(select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True)))
        if c.programa_id in (None, est.programa_id)
    ]
    if not cals:
        raise Conflict(
            f"No hay un calendario académico activo para el semestre {plan.semestre_academico}. Pida a la administración "
            "que configure las fechas de los cortes C1, C2 y C3 (Calendario académico) y vuelva a intentarlo.",
            "CALENDARIO_NO_CONFIGURADO",
        )
    cals.sort(key=lambda c: (c.semestre_academico != plan.semestre_academico, c.programa_id is None, -c.id))
    return cals[0]


def fechas_cortes(cal: CalendarioAcademico) -> dict[str, date]:
    return {"C1": cal.fecha_c1, "C2": cal.fecha_c2, "C3": cal.fecha_c3}


def seguimientos_por_corte(db: Session, plan_id: int) -> dict[str, Seguimiento]:
    return {str(s.corte): s for s in db.scalars(select(Seguimiento).where(Seguimiento.plan_id == plan_id))}


def _resumen_corte(db: Session, plan: PlanMaarTea, corte: str, ajustes: list[AjusteRazonable]) -> dict:
    cnt = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0}
    ids = {a.id for a in ajustes}
    for reg, c in sem.registros_del_plan(db, plan.id):
        if c == corte and reg.ajuste_id in ids and reg.semaforo is not None:
            cnt[str(reg.semaforo)] += 1
    valorados = sum(cnt.values())
    return {**cnt, "SIN_VALORAR": len(ajustes) - valorados, "total": len(ajustes)}


def bloqueo_apertura(db: Session, plan: PlanMaarTea, corte: str, segs: dict[str, Seguimiento]) -> dict | None:
    """Motivo por el que NO se puede abrir el corte (None = se puede)."""
    if plan.estado not in ESTADOS_PLAN_SEGUIMIENTO:
        return {"code": "PLAN_NO_EN_SEGUIMIENTO",
                "detail": "El seguimiento (F8) solo se registra con el plan en IMPLEMENTACION o SEGUIMIENTO "
                          f"(el plan está en {plan.estado})."}
    prev = sem.corte_anterior(corte)
    if prev and prev in segs and not segs[prev].cerrado:
        return {"code": "CORTE_ANTERIOR_ABIERTO",
                "detail": f"Primero cierre el corte {prev}: tiene el seguimiento abierto."}
    pendientes = sem.rojos_sin_rediseno(db, plan.id, antes_de=corte)
    if pendientes:
        return {"code": "REDISENO_PENDIENTE",
                "detail": "Hay ajustes en ROJO sin rediseño registrado. Registre el rediseño antes de pasar al siguiente "
                          f"corte ({len(pendientes)} pendiente(s)).",
                "ajuste_ids": [r.ajuste_id for r in pendientes]}
    return None


def estado_cortes(db: Session, plan: PlanMaarTea, cal: CalendarioAcademico, hoy: date | None = None, *,
                  ajuste_ids: set[int] | None = None) -> list[dict]:
    hoy = hoy or date.today()
    segs = seguimientos_por_corte(db, plan.id)
    fechas = fechas_cortes(cal)
    ajustes = sem.ajustes_activos(db, plan.id, ajuste_ids)
    out = []
    for c in CORTES:
        seg = segs.get(c)
        estado = "FUTURO" if seg is None else ("CERRADO" if seg.cerrado else "ABIERTO")
        bloqueo = bloqueo_apertura(db, plan, c, segs) if seg is None else None
        out.append({
            "corte": c, "fecha_corte": fechas[c].isoformat(), "estado": estado,
            "seguimiento_id": seg.id if seg else None, "cerrado": bool(seg and seg.cerrado),
            "vencido": seg is None and fechas[c] < hoy,
            "dias_restantes": (fechas[c] - hoy).days,
            "semaforo_estado": str(seg.semaforo_estado) if seg and seg.semaforo_estado else None,
            "resumen": _resumen_corte(db, plan, c, ajustes) if seg else None,
            "puede_abrir": seg is None and bloqueo is None, "bloqueo": bloqueo,
        })
    return out


# ============================================================================ abrir / actualizar corte
_CAMPOS_CORTE = ("participantes_ids", "descripcion_situacion_actual", "funcionamiento_apoyos", "dificultades_emergentes",
                 "ajustes_recomendados", "observaciones_generales")


def abrir_corte(db: Session, plan: PlanMaarTea, est: Estudiante, corte: str, actor: Usuario, datos: dict,
                request=None, hoy: date | None = None) -> tuple[Seguimiento, bool]:
    """Crea el SEGUIMIENTO del corte (o devuelve el existente abierto). Devuelve (seguimiento, creado)."""
    cal = calendario_para(db, plan, est)  # 409 si falta calendario
    segs = seguimientos_por_corte(db, plan.id)
    if corte in segs:
        if segs[corte].cerrado:
            raise Conflict(f"El corte {corte} ya está cerrado; no se puede volver a abrir.", "CORTE_CERRADO")
        return segs[corte], False
    bloqueo = bloqueo_apertura(db, plan, corte, segs)
    if bloqueo:
        raise Conflict(bloqueo["detail"], bloqueo["code"], extra={k: v for k, v in bloqueo.items() if k == "ajuste_ids"} or None)
    fechas = fechas_cortes(cal)
    sig = sem.corte_siguiente(corte)
    seg = Seguimiento(
        estudiante_id=est.id, plan_id=plan.id, corte=corte, semestre_academico=plan.semestre_academico,
        calendario_id=cal.id, fecha_seguimiento=datos.get("fecha_seguimiento") or (hoy or date.today()),
        profesional_responsable_id=actor.id, version_plan=plan.version,
        fecha_proximo_seguimiento=fechas[sig] if sig else None, cerrado=False,
    )
    for k in _CAMPOS_CORTE:
        if datos.get(k) is not None:
            setattr(seg, k, datos[k])
    db.add(seg)
    if str(plan.estado) == EstadoPlanEnum.IMPLEMENTACION:
        assert_transition(plan.estado, EstadoPlanEnum.SEGUIMIENTO)
        plan.estado = EstadoPlanEnum.SEGUIMIENTO
    db.flush()
    audit.log(db, actor, "SEGUIMIENTO_ABIERTO", "seguimiento", seg.id, {"plan_id": plan.id, "corte": corte},
              request=request, estudiante_id=est.id)
    return seg, True


def actualizar_corte(db: Session, seg: Seguimiento, datos: dict, actor: Usuario, request=None) -> Seguimiento:
    exigir_abierto(seg)
    for k in (*_CAMPOS_CORTE, "fecha_seguimiento"):
        if k in datos and (datos[k] is not None or k != "fecha_seguimiento"):
            setattr(seg, k, datos[k])
    audit.log(db, actor, "SEGUIMIENTO_ACTUALIZADO", "seguimiento", seg.id, {"campos": sorted(datos)},
              request=request, estudiante_id=seg.estudiante_id)
    db.flush()
    return seg


def exigir_abierto(seg: Seguimiento) -> None:
    if seg.cerrado:
        raise Conflict(f"El corte {seg.corte} ya está cerrado: no se puede modificar.", "CORTE_CERRADO")


def get_seguimiento_or_404(db: Session, plan_id: int, corte: str) -> Seguimiento:
    seg = seguimientos_por_corte(db, plan_id).get(str(corte))
    if seg is None:
        raise NotFound(f"El corte {corte} todavía no se ha abierto para este plan. Ábralo primero.", "CORTE_NO_ABIERTO")
    return seg


def exigir_ajuste_del_plan(db: Session, plan: PlanMaarTea, ajuste_id: int) -> AjusteRazonable:
    a = db.get(AjusteRazonable, ajuste_id)
    if a is None or a.plan_id != plan.id:
        raise NotFound("Ese ajuste no pertenece a este plan.", "AJUSTE_NO_ENCONTRADO")
    return a


# ============================================================================ registro por ajuste
def registrar_ajuste(db: Session, plan: PlanMaarTea, est: Estudiante, seg: Seguimiento, ajuste: AjusteRazonable,
                     actor: Usuario, datos: dict, request=None) -> tuple[RegistroSeguimientoAjuste, dict]:
    """Bienestar registra implementacion, frecuencia, resultado observado y semaforo del ajuste en el corte."""
    exigir_abierto(seg)
    reg = db.scalar(select(RegistroSeguimientoAjuste).where(
        RegistroSeguimientoAjuste.seguimiento_id == seg.id, RegistroSeguimientoAjuste.ajuste_id == ajuste.id))
    if reg is None:
        reg = RegistroSeguimientoAjuste(seguimiento_id=seg.id, ajuste_id=ajuste.id, corte=seg.corte,
                                        registrado_por_id=actor.id, rol_registrante=str(actor.rol))
        db.add(reg)
    nuevo = datos.get("semaforo")
    resultado = datos["resultado_observado"] if "resultado_observado" in datos else reg.resultado_observado
    if nuevo is not None and str(nuevo) in ("ROJO", "AMARILLO") and not (resultado or "").strip():
        raise Unprocessable(
            f"Para marcar un ajuste en {nuevo} describa el resultado observado: qué pasó y por qué no funciona del todo.",
            "RESULTADO_OBSERVADO_REQUERIDO",
        )
    for k in ("implementado", "frecuencia_implementacion", "resultado_observado"):
        if k in datos:
            setattr(reg, k, datos[k])
    reg.registrado_por_id, reg.rol_registrante = actor.id, str(actor.rol)
    db.flush()
    cal = db.get(CalendarioAcademico, seg.calendario_id) if seg.calendario_id else None
    fecha_limite = seg.fecha_proximo_seguimiento or (cal.fecha_fin if cal else None)
    res = sem.aplicar_semaforo(db, registro=reg, ajuste=ajuste, plan=plan, est=est, nuevo=nuevo, actor=actor,
                               fecha_limite=fecha_limite, request=request)
    advertencias = []
    if str(reg.semaforo or "") == "VERDE" and reg.percepcion_estudiante is not None and str(reg.percepcion_estudiante) == "NEGATIVA":
        advertencias.append("El estudiante reportó una percepción NEGATIVA de este ajuste; revise si VERDE es lo correcto.")
    res["advertencias"] = advertencias
    return reg, res


def registrar_percepcion(db: Session, plan: PlanMaarTea, seg: Seguimiento, ajuste: AjusteRazonable, actor: Usuario,
                         percepcion: str, comentario: str | None, request=None) -> RegistroSeguimientoAjuste:
    """HU-21: SOLO el estudiante (dueno del plan) escribe su percepcion; nadie mas la modifica."""
    exigir_abierto(seg)
    reg = db.scalar(select(RegistroSeguimientoAjuste).where(
        RegistroSeguimientoAjuste.seguimiento_id == seg.id, RegistroSeguimientoAjuste.ajuste_id == ajuste.id))
    if reg is None:
        reg = RegistroSeguimientoAjuste(seguimiento_id=seg.id, ajuste_id=ajuste.id, corte=seg.corte,
                                        registrado_por_id=actor.id, rol_registrante=str(actor.rol))
        db.add(reg)
    reg.percepcion_estudiante = percepcion
    reg.comentario_estudiante = comentario
    audit.log(db, actor, "PERCEPCION_REGISTRADA", "registro_seguimiento_ajuste", reg.id,
              {"ajuste_id": ajuste.id, "corte": str(seg.corte), "percepcion": str(percepcion)},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return reg


# ============================================================================ registros, evidencias, barreras emergentes
def agregar_registro(db: Session, seg: Seguimiento, datos: dict, actor: Usuario, request=None) -> RegistroSeguimiento:
    exigir_abierto(seg)
    r = RegistroSeguimiento(seguimiento_id=seg.id, **datos)
    db.add(r)
    db.flush()
    audit.log(db, actor, "REGISTRO_SEGUIMIENTO_CREADO", "registro_seguimiento", r.id, {"corte": str(seg.corte)},
              request=request, estudiante_id=seg.estudiante_id)
    return r


def agregar_evidencia(db: Session, seg: Seguimiento, datos: dict, actor: Usuario, request=None) -> EvidenciaEfectividad:
    exigir_abierto(seg)
    resultados = datos.pop("resultados", [])
    ev = EvidenciaEfectividad(seguimiento_id=seg.id, **datos)
    db.add(ev)
    db.flush()
    for r in resultados:
        db.add(ResultadoIndicador(evidencia_id=ev.id, **r))
    db.flush()
    audit.log(db, actor, "EVIDENCIA_EFECTIVIDAD_CREADA", "evidencia_efectividad", ev.id, {"corte": str(seg.corte)},
              request=request, estudiante_id=seg.estudiante_id)
    return ev


def soft_delete(db: Session, obj: Any, actor: Usuario, motivo: str, estudiante_id: int, request=None) -> None:
    obj.soft_delete(actor.id, motivo)
    audit.log(db, actor, "ELIMINACION_LOGICA", obj.__tablename__, obj.id, {"motivo": motivo}, request=request,
              estudiante_id=estudiante_id)
    db.flush()


def registrar_barrera_emergente(db: Session, plan: PlanMaarTea, est: Estudiante, seg: Seguimiento, actor: Usuario,
                                datos: dict, request=None) -> dict:
    """Crea una BARRERA_IDENTIFICADA (F4) detectada en el F8 y deja la propuesta de ajuste en el corte."""
    exigir_abierto(seg)
    ajuste = exigir_ajuste_del_plan(db, plan, datos["ajuste_id"]) if datos.get("ajuste_id") else None
    tipo = str(datos["tipo_barrera"])
    if tipo == "SOCIAL" and not (datos.get("propuesta_respuesta_institucional") or "").strip():
        raise Unprocessable("Las barreras sociales requieren una propuesta de respuesta institucional (RF-19).",
                            "PROPUESTA_INSTITUCIONAL_REQUERIDA")
    barrera = BarreraIdentificada(
        estudiante_id=est.id, tipo_barrera=datos["tipo_barrera"], escenario=datos.get("escenario"),
        descripcion_barrera=datos["descripcion_barrera"], severidad=datos["severidad"], frecuencia=datos["frecuencia"],
        fecha_identificacion=date.today(), semestre_academico=plan.semestre_academico, registrada_por_id=actor.id,
        contexto_aparicion=f"Detectada en el seguimiento F8, corte {seg.corte}",
    )
    db.add(barrera)
    db.flush()
    if tipo == "SOCIAL":
        db.add(BarreraSocial(barrera_id=barrera.id, descripcion_dificultad=datos["descripcion_barrera"],
                             propuesta_respuesta_institucional=datos["propuesta_respuesta_institucional"]))
    propuesta = datos.get("propuesta_ajuste")
    entrada = {
        "barrera_id": barrera.id, "tipo_barrera": tipo, "ajuste_id": ajuste.id if ajuste else None,
        "propuesta_ajuste": (propuesta if propuesta else None), "registrada_por_id": actor.id,
        "fecha": date.today().isoformat(),
    }
    if entrada["propuesta_ajuste"]:
        entrada["propuesta_ajuste"] = {**propuesta, "tipo_ajuste": str(propuesta["tipo_ajuste"])}
    seg.barreras_emergentes = [*(seg.barreras_emergentes or []), entrada]
    linea = f"Nueva barrera ({tipo}): {datos['descripcion_barrera']}"
    if propuesta:
        linea += f" | Ajuste propuesto: {propuesta['nombre_ajuste']}"
    seg.ajustes_recomendados = f"{seg.ajustes_recomendados}\n{linea}" if seg.ajustes_recomendados else linea
    if ajuste is not None:
        reg = db.scalar(select(RegistroSeguimientoAjuste).where(
            RegistroSeguimientoAjuste.seguimiento_id == seg.id, RegistroSeguimientoAjuste.ajuste_id == ajuste.id))
        if reg is not None:
            reg.nueva_barrera_detectada = (f"{reg.nueva_barrera_detectada}\n" if reg.nueva_barrera_detectada else "") + linea
    audit.log(db, actor, "BARRERA_EMERGENTE_REGISTRADA", "barrera_identificada", barrera.id,
              {"plan_id": plan.id, "corte": str(seg.corte), "tipo": tipo}, request=request, estudiante_id=est.id)
    db.flush()
    return {
        "barrera_id": barrera.id, "tipo_barrera": tipo, "propuesta_ajuste": entrada["propuesta_ajuste"],
        "siguiente_paso": {
            "titulo": "Actualice el plan con el ajuste propuesto",
            "descripcion": "La barrera quedó en el mapa de barreras (F4). Concerte con el estudiante el ajuste nuevo y "
                           "agréguelo al Plan MAAR-TEA (se genera una nueva versión).",
            "ruta_frontend": ruta_front(Rol.BIENESTAR, "plan", estudiante_id=est.id, plan_id=plan.id),
        },
    }


# ============================================================================ cierre
def cerrar_corte(db: Session, plan: PlanMaarTea, est: Estudiante, seg: Seguimiento, actor: Usuario, request=None) -> dict:
    exigir_abierto(seg)
    ajustes = sem.ajustes_activos(db, plan.id)
    regs = {r.ajuste_id: r for r, c in sem.registros_del_plan(db, plan.id) if c == str(seg.corte)}
    sin = [a for a in ajustes if a.id not in regs or regs[a.id].semaforo is None]
    if sin:
        raise Conflict(
            "Faltan ajustes por valorar con el semáforo: " + ", ".join(f"«{a.nombre_ajuste}»" for a in sin[:5])
            + (" …" if len(sin) > 5 else "") + ". Valore todos los ajustes antes de cerrar el corte.",
            "AJUSTES_SIN_SEMAFORO", extra={"ajuste_ids": [a.id for a in sin]},
        )
    seg.cerrado = True
    db.flush()
    agregado = sem.recalcular_caches(db, plan)
    audit.log(db, actor, "SEGUIMIENTO_CERRADO", "seguimiento", seg.id,
              {"plan_id": plan.id, "corte": str(seg.corte), "semaforo": agregado}, request=request, estudiante_id=est.id)
    pendientes = sem.rojos_sin_rediseno(db, plan.id)
    if str(seg.corte) == "C3":
        paso = {"titulo": "Evalúe la efectividad del plan (F9)",
                "descripcion": "Ya están los tres cortes. Cree el borrador de la evaluación y decida qué ajustes se mantienen, modifican o retiran.",
                "ruta_frontend": ruta_front(Rol.BIENESTAR, "f9", estudiante_id=est.id, plan_id=plan.id)}
    elif pendientes:
        paso = {"titulo": "Registre el rediseño de los ajustes en ROJO",
                "descripcion": "No podrá abrir el siguiente corte hasta registrar el rediseño de cada ajuste en rojo.",
                "ruta_frontend": ruta_front(Rol.BIENESTAR, "seguimiento", estudiante_id=est.id, plan_id=plan.id)}
    else:
        paso = {"titulo": f"Prepare el corte {sem.corte_siguiente(seg.corte)}",
                "descripcion": "Cuando llegue la fecha del siguiente corte, ábralo para registrar el seguimiento.",
                "ruta_frontend": ruta_front(Rol.BIENESTAR, "seguimiento", estudiante_id=est.id, plan_id=plan.id)}
    return {"semaforo_agregado": agregado, "rojos_sin_rediseno": [r.ajuste_id for r in pendientes],
            "siguiente_paso": paso}


# ============================================================================ indicadores
def tasa_implementacion(db: Session, plan_id: int, hasta: str = "C2") -> dict:
    """Indicador D6: % de ajustes implementados al corte `hasta` (meta >= 80 % al C2).

    Un ajuste cuenta como implementado si en el ultimo registro (corte <= `hasta`) con dato `implementado` es True.
    """
    ajustes = sem.ajustes_activos(db, plan_id)
    limite = CORTES.index(hasta)
    ultimo: dict[int, bool] = {}
    hay_corte = False
    for reg, corte in sem.registros_del_plan(db, plan_id):
        i = CORTES.index(corte)
        if i > limite:
            continue
        if i == limite:
            hay_corte = True
        if reg.implementado is not None:
            ultimo[reg.ajuste_id] = bool(reg.implementado)
    total = len(ajustes)
    impl = sum(1 for a in ajustes if ultimo.get(a.id))
    valor = round(100 * impl / total, 1) if total else None
    return {"indicador": "D6", "valor": valor, "implementados": impl, "total": total, "meta": META_PORCENTAJE,
            "cumple": bool(valor is not None and valor >= META_PORCENTAJE), "corte_referencia": hasta,
            "datos_suficientes": hay_corte}


def porcentaje_verde(db: Session, plan_id: int) -> dict:
    """Indicador D8: % de ajustes en VERDE (ultimo semaforo valorado; meta >= 80 % al C3)."""
    ajustes = sem.ajustes_activos(db, plan_id)
    ultimo: dict[int, str] = {}
    hay_c3 = False
    for reg, corte in sem.registros_del_plan(db, plan_id):
        if corte == "C3":
            hay_c3 = True
        if reg.semaforo is not None:
            ultimo[reg.ajuste_id] = str(reg.semaforo)  # ordenado por corte: el ultimo gana
    total = len(ajustes)
    verdes = sum(1 for a in ajustes if ultimo.get(a.id) == "VERDE")
    valor = round(100 * verdes / total, 1) if total else None
    return {"indicador": "D8", "valor": valor, "verdes": verdes, "total": total, "meta": META_PORCENTAJE,
            "cumple": bool(valor is not None and valor >= META_PORCENTAJE), "corte_referencia": "C3",
            "datos_suficientes": hay_c3}


# ============================================================================ serializacion
def _ajuste_resumen(a: AjusteRazonable) -> dict:
    return {"ajuste_id": a.id, "nombre_ajuste": a.nombre_ajuste, "tipo_ajuste": str(a.tipo_ajuste),
            "asignatura_id": a.asignatura_id, "responsable_id": a.responsable_id}


def serializar_corte(db: Session, plan: PlanMaarTea, seg: Seguimiento, *, ajuste_ids: set[int] | None = None,
                     vista: str = "completa") -> dict:
    ajustes = sem.ajustes_activos(db, plan.id, ajuste_ids)
    regs = {r.ajuste_id: r for r, c in sem.registros_del_plan(db, plan.id) if c == str(seg.corte)}
    filas = [{**_ajuste_resumen(a), "registro": sem.serializar_registro(regs[a.id], vista=vista) if a.id in regs else None}
             for a in ajustes]
    out: dict[str, Any] = {
        "seguimiento_id": seg.id, "plan_id": plan.id, "corte": str(seg.corte), "cerrado": seg.cerrado,
        "estado": "CERRADO" if seg.cerrado else "ABIERTO", "fecha_seguimiento": seg.fecha_seguimiento.isoformat(),
        "fecha_proximo_seguimiento": seg.fecha_proximo_seguimiento.isoformat() if seg.fecha_proximo_seguimiento else None,
        "semaforo_estado": str(seg.semaforo_estado) if seg.semaforo_estado else None,
        "resumen": _resumen_corte(db, plan, str(seg.corte), ajustes), "ajustes": filas,
    }
    if vista == "docente":
        return out
    out.update(
        version_plan=seg.version_plan, profesional_responsable_id=seg.profesional_responsable_id,
        participantes_ids=seg.participantes_ids or [],
        descripcion_situacion_actual=seg.descripcion_situacion_actual, funcionamiento_apoyos=seg.funcionamiento_apoyos,
        dificultades_emergentes=seg.dificultades_emergentes, ajustes_recomendados=seg.ajustes_recomendados,
        observaciones_generales=seg.observaciones_generales,
        barreras_emergentes=seg.barreras_emergentes or [],
        registros=[{"id": r.id, "tipo_registro": str(r.tipo_registro), "descripcion_metodologia": r.descripcion_metodologia,
                    "fuentes_informacion": r.fuentes_informacion, "created_at": r.created_at.isoformat()}
                   for r in db.scalars(select(RegistroSeguimiento).where(RegistroSeguimiento.seguimiento_id == seg.id)
                                       .order_by(RegistroSeguimiento.id))],
        evidencias=[_evidencia(db, e) for e in db.scalars(select(EvidenciaEfectividad)
                                                          .where(EvidenciaEfectividad.seguimiento_id == seg.id)
                                                          .order_by(EvidenciaEfectividad.id))],
        rojos_sin_rediseno=[r.ajuste_id for r in sem.rojos_sin_rediseno(db, plan.id)],
    )
    return out


def _evidencia(db: Session, e: EvidenciaEfectividad) -> dict:
    res = db.scalars(select(ResultadoIndicador).where(ResultadoIndicador.evidencia_id == e.id).order_by(ResultadoIndicador.id))
    return {
        "id": e.id, "tipo_evidencia": str(e.tipo_evidencia), "descripcion_evidencia": e.descripcion_evidencia,
        "fuente_evidencia": e.fuente_evidencia,
        "dato_cuantitativo": float(e.dato_cuantitativo) if isinstance(e.dato_cuantitativo, Decimal) else e.dato_cuantitativo,
        "periodo_medicion": e.periodo_medicion,
        "resultados": [{"id": r.id, "dimension_resultado": str(r.dimension_resultado),
                        "indicador_especifico": r.indicador_especifico, "valor_logrado": r.valor_logrado,
                        "meta_establecida": r.meta_establecida, "porcentaje_cumplimiento": r.porcentaje_cumplimiento,
                        "interpretacion": r.interpretacion} for r in res],
    }


# ============================================================================ API para run_daily_jobs (slice A)
def cortes_proximos(db: Session, hoy: date, dias: tuple[int, ...] = (7, 1)) -> list[dict]:
    """Cortes de calendarios ACTIVOS que caen exactamente dentro de `dias` dias a partir de `hoy`."""
    out = []
    for cal in db.scalars(select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True))):
        for corte, f in fechas_cortes(cal).items():
            d = (f - hoy).days
            if d in dias:
                out.append({"corte": corte, "fecha_corte": f, "dias_restantes": d, "semestre": cal.semestre_academico,
                            "calendario_id": cal.id, "programa_id": cal.programa_id})
    return out


def pendientes_de_corte(db: Session, corte: str, *, calendario_id: int | None = None) -> list[dict]:
    """Planes vigentes (IMPLEMENTACION/SEGUIMIENTO) cuyo F8 del corte no esta cerrado: a quienes recordar (RF-30)."""
    corte = str(corte)
    cals = [c for c in db.scalars(select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True)))
            if calendario_id is None or c.id == calendario_id]
    out = []
    for cal in cals:
        stmt = select(PlanMaarTea, Estudiante).join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id).where(
            PlanMaarTea.estado.in_(ESTADOS_PLAN_SEGUIMIENTO), PlanMaarTea.semestre_academico == cal.semestre_academico)
        if cal.programa_id is not None:
            stmt = stmt.where(Estudiante.programa_id == cal.programa_id)
        for plan, est in db.execute(stmt).all():
            seg = seguimientos_por_corte(db, plan.id).get(corte)
            if seg is not None and seg.cerrado:
                continue
            ajustes = sem.ajustes_activos(db, plan.id)
            docentes: list[int] = []
            for a in ajustes:
                docentes.extend(u.id for u in sem.docentes_responsables(db, a, plan.semestre_academico))
            b = sem.bienestar_responsable(db, est, plan, None)
            out.append({
                "plan_id": plan.id, "estudiante_id": est.id, "estudiante_usuario_id": est.usuario_id,
                "bienestar_usuario_id": b.id if b else None, "docente_usuario_ids": list(dict.fromkeys(docentes)),
                "ajuste_ids": [a.id for a in ajustes], "estado_corte": "SIN_ABRIR" if seg is None else "ABIERTO",
                "calendario_id": cal.id, "fecha_corte": fechas_cortes(cal)[corte], "semestre": cal.semestre_academico,
            })
    return out


__all__ = [
    "CORTES", "abrir_corte", "actualizar_corte", "agregar_evidencia", "agregar_registro", "bloqueo_apertura",
    "calendario_para", "cerrar_corte", "cortes_proximos", "estado_cortes", "fechas_cortes", "get_plan_or_404",
    "get_seguimiento_or_404", "pendientes_de_corte", "porcentaje_verde", "registrar_ajuste",
    "registrar_barrera_emergente", "registrar_percepcion", "serializar_corte", "tasa_implementacion", "TipoAjuste",
    "utcnow",
]
