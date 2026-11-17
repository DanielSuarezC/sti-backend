"""«Mi ruta» (12 pasos MAAR-TEA), «lo que sigue» y pendientes por estudiante. Todo se calcula en el backend (P6)
inspeccionando los datos existentes: consentimiento, AQ-10 (solo si fue aplicado, nunca el puntaje), F1-F5, sugerencias DUA,
plan, matriz F7, seguimiento por corte, F9 y F10.

# OWNER: slice C2

Contrato de rutas del frontend (`ruta_frontend`): ver `ruta_front()` y docs/api/slice_c2.md.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import student_has_consent
from app.models.apoyos import Apoyo
from app.models.caracterizacion import Caracterizacion, Fortaleza, PerfilFortalezas
from app.models.consentimiento import RespuestaAQ10
from app.models.contexto import ContextoUniversitario
from app.models.dua import SugerenciaDua
from app.models.enums import EstadoNotaContinuidad, Rol
from app.models.evaluacion import EvaluacionPlan, NotaContinuidad
from app.models.mapa import BarreraIdentificada, Facilitador
from app.models.plan import FirmaPlan, PlanMaarTea
from app.models.seguimiento import Seguimiento
from app.models.usuarios import Estudiante, Usuario

PLAN_FIRMADO = ("APROBADO", "IMPLEMENTACION", "SEGUIMIENTO", "FINALIZADO", "ARCHIVADO")
PLAN_VIGENTE = ("IMPLEMENTACION", "SEGUIMIENTO", "FINALIZADO", "ARCHIVADO")
PLAN_EN_CURSO = ("BORRADOR", "EN_CONCERTACION", "EN_NEGOCIACION", "ESCALADO_COMITE", "PENDIENTE_VALIDACION",
                 "PENDIENTE_FIRMAS")

#: (numero, nombre, descripcion, modulo, formato, clave de ruta)
PASOS: list[tuple[int, str, str, str, str, str]] = [
    (1, "Conocer al estudiante", "Caracterización funcional como aprendiz: comunicación, perfil sensorial, autonomía y apoyos previos.", "M2", "F1", "f1"),
    (2, "Reconocer fortalezas", "Capacidades, intereses, estrategias propias de aprendizaje y metas.", "M2", "F2", "f2"),
    (3, "Comprender el contexto", "Análisis de los escenarios universitarios del semestre (aula, campus, virtualidad, laboratorios, prácticas...).", "M3", "F3", "f3"),
    (4, "Identificar barreras", "Obstáculos del entorno por tipo y escenario. Las barreras son del entorno, no de la persona.", "M4", "F4", "f4"),
    (5, "Identificar facilitadores", "Recursos y condiciones que ya favorecen la experiencia.", "M4", "F5", "f5"),
    (6, "Aplicar DUA", "Estrategias universales sugeridas del catálogo institucional, revisadas por Bienestar.", "M3", "F6", "sugerencias"),
    (7, "Barreras persistentes", "Barreras que siguen después de las medidas DUA: justifican los ajustes individuales.", "M4", "F4", "f4"),
    (8, "Definir ajustes razonables", "Ajustes individuales concertados con el estudiante y firmados.", "M5", "F6", "plan"),
    (9, "Implementar apoyos", "Matriz de responsabilidades: quién, qué recurso y con qué frecuencia.", "M5", "F7", "matriz"),
    (10, "Hacer seguimiento", "Registro por corte (C1, C2, C3) con semáforo verde, amarillo o rojo por ajuste.", "M6", "F8", "seguimiento"),
    (11, "Evaluar y modificar", "Efectividad del semestre y decisión por ajuste: mantener, modificar o retirar.", "M7", "F9", "f9"),
    (12, "Favorecer la trayectoria", "Actualización del plan, trayectoria y notas de continuidad para el siguiente semestre.", "M8", "F10", "f10"),
]

_EST = {"consentimiento": "/estudiante/consentimiento", "aq10": "/estudiante/aq10", "f1": "/estudiante/perfil",
        "f2": "/estudiante/perfil", "f3": "/estudiante/mi-ruta", "f4": "/estudiante/barreras",
        "f5": "/estudiante/barreras", "sugerencias": "/estudiante/mi-ruta", "plan": "/estudiante/plan",
        "matriz": "/estudiante/plan", "seguimiento": "/estudiante/seguimiento", "f9": "/estudiante/evaluacion",
        "f10": "/estudiante/continuidad", "ruta": "/estudiante/mi-ruta", "inasistencia": "/estudiante/mi-ruta"}


def ruta_front(rol: Rol | str, clave: str, *, estudiante_id: int | None = None, plan_id: int | None = None,
               ajuste_id: int | None = None) -> str:
    """Ruta del frontend para la `clave` de pantalla segun el rol que la abre.

    claves: consentimiento, aq10, f1..f5, sugerencias, plan, matriz, seguimiento, f9, f10, ruta, inasistencia.
    """
    rol = str(rol)
    if rol == "ESTUDIANTE":
        return _EST.get(clave, "/estudiante")
    if rol == "BIENESTAR":
        if estudiante_id is None:
            return "/bienestar"
        return f"/bienestar/estudiantes/{estudiante_id}" + ("" if clave == "ruta" else f"/{clave}")
    if rol == "COORDINADOR":
        if clave in ("plan", "matriz") and plan_id:
            return f"/coordinador/planes/{plan_id}"
        return f"/coordinador/estudiantes/{estudiante_id}" if estudiante_id else "/coordinador"
    if rol == "DOCENTE":
        return f"/docente/ajustes/{ajuste_id}" if ajuste_id else "/docente"
    return {"FAMILIAR": "/familiar", "ADMIN": "/admin"}.get(rol, "/")


# ============================================================================ hechos
def plan_vigente_de(db: Session, est_id: int) -> PlanMaarTea | None:
    planes = list(db.scalars(select(PlanMaarTea).where(PlanMaarTea.estudiante_id == est_id).order_by(PlanMaarTea.id.desc())))
    return next((p for p in planes if str(p.estado) != "ARCHIVADO"), planes[0] if planes else None)


def _n(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def _hechos(db: Session, est: Estudiante) -> dict:
    h: dict = {"est": est}
    user = db.get(Usuario, est.usuario_id)
    h["cuenta"] = str(user.estado) if user else None
    h["consent"] = student_has_consent(db, est.id)
    aq = db.execute(select(RespuestaAQ10.supera_umbral, RespuestaAQ10.aplicado_at).where(
        RespuestaAQ10.estudiante_id == est.id).order_by(RespuestaAQ10.id.desc()).limit(1)).first()
    h["aq10"] = aq is not None
    h["aq10_activa_ruta"] = bool(aq and aq[0])
    estados_car = [str(x) for x in db.scalars(select(Caracterizacion.estado).where(Caracterizacion.estudiante_id == est.id))]
    h["f1_completa"], h["f1_en_curso"] = "COMPLETA" in estados_car, bool(estados_car)
    perfiles = list(db.scalars(select(PerfilFortalezas.id).where(PerfilFortalezas.estudiante_id == est.id)))
    h["f2_en_curso"] = bool(perfiles)
    h["f2_completa"] = bool(perfiles) and bool(db.scalar(select(func.count(Fortaleza.id)).where(
        Fortaleza.perfil_fortalezas_id.in_(perfiles))))
    plan = plan_vigente_de(db, est.id)
    h["plan"] = plan
    semestre = plan.semestre_academico if plan else None
    ctx = select(ContextoUniversitario.id).where(ContextoUniversitario.estudiante_id == est.id)
    h["f3"] = bool(_n(db, ctx.where(ContextoUniversitario.semestre_academico == semestre) if semestre else ctx))
    barreras = [str(b) for b in db.scalars(select(BarreraIdentificada.estado).where(BarreraIdentificada.estudiante_id == est.id))]
    h["n_barreras"], h["n_barreras_sin_revisar"] = len(barreras), sum(1 for b in barreras if b == "IDENTIFICADA")
    h["n_facilitadores"] = _n(db, select(Facilitador.id).where(Facilitador.estudiante_id == est.id))
    sug = [str(s) for s in db.scalars(select(SugerenciaDua.estado).where(SugerenciaDua.estudiante_id == est.id))]
    h["n_sugerencias"], h["n_sugerencias_propuestas"] = len(sug), sum(1 for s in sug if s == "PROPUESTA")
    h.update(segs={}, ev=None, nota=None, firmas=set(), n_apoyos=0, rojos=[], tareas=[], percepciones_faltantes=0, n_ajustes=0)
    if plan:
        from app.services import semaforo as sem

        h["n_ajustes"] = len(sem.ajustes_activos(db, plan.id))
        h["n_apoyos"] = _n(db, select(Apoyo.id).where(Apoyo.plan_id == plan.id))
        h["segs"] = {str(s.corte): s for s in db.scalars(select(Seguimiento).where(Seguimiento.plan_id == plan.id))}
        h["ev"] = db.scalar(select(EvaluacionPlan).where(EvaluacionPlan.plan_id == plan.id).order_by(EvaluacionPlan.id.desc()))
        h["firmas"] = {str(f.rol_firmante) for f in db.scalars(select(FirmaPlan).where(
            FirmaPlan.plan_id == plan.id, FirmaPlan.version == plan.version))}
        h["rojos"] = sem.rojos_sin_rediseno(db, plan.id)
        regs = sem.registros_del_plan(db, plan.id)
        h["tareas"] = [r for r, _ in regs if r.tarea_concertacion and r.tarea_concertacion.get("estado") == "ABIERTA"]
        abierto = next((s for s in h["segs"].values() if not s.cerrado), None)
        if abierto is not None:
            con_perc = {r.ajuste_id for r, c in regs if c == str(abierto.corte) and r.percepcion_estudiante is not None}
            h["percepciones_faltantes"] = max(0, h["n_ajustes"] - len(con_perc))
    h["nota"] = db.scalar(select(NotaContinuidad).where(NotaContinuidad.estudiante_id == est.id).order_by(NotaContinuidad.id.desc()))
    return h


# ============================================================================ pasos
def _pasos(h: dict) -> list[dict]:
    plan = h["plan"]
    pe = str(plan.estado) if plan else None
    segs = h["segs"]
    ev = h["ev"]
    nota = h["nota"]
    c3 = segs.get("C3")
    estado_cortes = ", ".join(f"{c} {'cerrado' if segs[c].cerrado else 'abierto'}" for c in ("C1", "C2", "C3") if c in segs)
    # (completado, en_curso, detalle)
    flags = {
        1: (h["f1_completa"], h["f1_en_curso"], None),
        2: (h["f2_completa"], h["f2_en_curso"], None),
        3: (h["f3"], False, None),
        4: (h["n_barreras"] > 0, False, f"{h['n_barreras']} barrera(s) registrada(s)" if h["n_barreras"] else None),
        5: (h["n_facilitadores"] > 0, False, f"{h['n_facilitadores']} facilitador(es)" if h["n_facilitadores"] else None),
        6: (h["n_sugerencias"] > 0 and h["n_sugerencias_propuestas"] == 0, h["n_sugerencias"] > 0,
            f"{h['n_sugerencias_propuestas']} sugerencia(s) por decidir" if h["n_sugerencias_propuestas"] else None),
        7: (h["n_barreras"] > 0 and h["n_barreras_sin_revisar"] == 0 and (h["n_sugerencias"] > 0 or pe in PLAN_FIRMADO), False,
            f"{h['n_barreras_sin_revisar']} barrera(s) por revisar" if h["n_barreras_sin_revisar"] else None),
        8: (pe in PLAN_FIRMADO, pe in PLAN_EN_CURSO, f"Plan en {pe}" if pe else None),
        9: (h["n_apoyos"] > 0 or pe in PLAN_VIGENTE, pe == "APROBADO", None),
        10: (bool(c3 and c3.cerrado), bool(segs) or pe in ("IMPLEMENTACION", "SEGUIMIENTO"), estado_cortes or None),
        11: (bool(ev and ev.estado == "CERRADA"), bool(ev), None),
        12: (bool(nota and str(nota.estado) == EstadoNotaContinuidad.APROBADA), bool(nota), None),
    }
    out, actual_marcado = [], False
    for num, nombre, desc, modulo, formato, clave in PASOS:
        completado, en_curso, detalle = flags[num]
        if completado:
            estado = "hecho"
        elif not actual_marcado and h["consent"]:
            estado, actual_marcado = "actual", True
        else:
            estado = "pendiente"
        out.append({"numero": num, "nombre": nombre, "descripcion": desc, "modulo": modulo, "formato": formato,
                    "estado": estado, "en_curso": bool(en_curso and not completado), "detalle": detalle, "_clave": clave})
    return out


# ============================================================================ pendientes
def _p(codigo, titulo, desc, clave, resp, prioridad="MEDIA", **extra) -> dict:
    return {"codigo": codigo, "titulo": titulo, "descripcion": desc, "_clave": clave, "responsables": resp,
            "prioridad": prioridad, **extra}


def _pendientes_brutos(db: Session, h: dict, hoy: date) -> list[dict]:
    est, plan = h["est"], h["plan"]
    pe = str(plan.estado) if plan else None
    out: list[dict] = []
    if h["cuenta"] == "PENDIENTE_ACTIVACION":
        return [_p("CUENTA_SIN_ACTIVAR", "La cuenta aún no está activada", "El estudiante no ha usado la invitación. Reenvíela desde Usuarios.", "ruta", ["BIENESTAR"], "ALTA")]
    if not h["consent"]:
        return [_p("F0", "Firmar el consentimiento informado (F0)", "Sin el F0 firmado no se puede continuar con ningún formato.", "consentimiento", ["ESTUDIANTE", "BIENESTAR"], "ALTA")]
    if not h["aq10"]:
        out.append(_p("AQ10", "Aplicar el tamizaje AQ-10", "Es una herramienta de tamizaje, no un diagnóstico.", "aq10", ["BIENESTAR", "ESTUDIANTE"]))
    if not h["f1_completa"]:
        out.append(_p("F1", "Completar la caracterización (F1)", "Conocer al estudiante como aprendiz.", "f1", ["BIENESTAR", "ESTUDIANTE"]))
    if not h["f2_completa"]:
        out.append(_p("F2", "Completar el perfil de fortalezas (F2)", "Fortalezas, intereses y metas.", "f2", ["BIENESTAR", "ESTUDIANTE"]))
    if not h["f3"]:
        out.append(_p("F3", "Analizar el contexto universitario (F3)", "Escenarios del semestre.", "f3", ["BIENESTAR", "COORDINADOR"]))
    if h["n_barreras"] == 0:
        out.append(_p("F4", "Registrar el mapa de barreras (F4)", "Obstáculos del entorno.", "f4", ["BIENESTAR", "ESTUDIANTE"]))
    if h["n_facilitadores"] == 0:
        out.append(_p("F5", "Registrar el mapa de facilitadores (F5)", "Lo que ya favorece al estudiante.", "f5", ["BIENESTAR", "ESTUDIANTE"]))
    if h["n_sugerencias_propuestas"]:
        out.append(_p("SUGERENCIAS_DUA", f"Decidir {h['n_sugerencias_propuestas']} sugerencia(s) DUA", "Aceptar, modificar o rechazar con motivo.", "sugerencias", ["BIENESTAR"]))
    if h["n_barreras_sin_revisar"] and h["n_sugerencias"] and not h["n_sugerencias_propuestas"]:
        out.append(_p("BARRERAS_PERSISTENTES", "Revisar qué barreras persisten tras el DUA", "Justifican los ajustes individuales.", "f4", ["BIENESTAR"]))
    if plan is None:
        if h["n_barreras"]:
            out.append(_p("PLAN_SIN_BORRADOR", "Elaborar el borrador del Plan MAAR-TEA", "Se arma con las barreras y las sugerencias DUA.", "plan", ["BIENESTAR"]))
        return out
    pid = plan.id
    resp_firmas = [r for r in ("ESTUDIANTE", "BIENESTAR", "COORDINADOR") if r not in h["firmas"]]
    por_estado = {
        "BORRADOR": ("PLAN_BORRADOR", "Terminar el borrador del plan y enviarlo al estudiante", ["BIENESTAR"]),
        "EN_CONCERTACION": ("PLAN_CONCERTACION", "Revisar y concertar el plan", ["ESTUDIANTE", "BIENESTAR"]),
        "EN_NEGOCIACION": ("PLAN_NEGOCIACION", "Resolver la objeción del estudiante sobre un ajuste", ["ESTUDIANTE", "BIENESTAR"]),
        "ESCALADO_COMITE": ("PLAN_COMITE", "Dar seguimiento al caso escalado al Comité de Inclusión", ["BIENESTAR"]),
        "PENDIENTE_VALIDACION": ("PLAN_VALIDACION", "Validar el plan", ["COORDINADOR", "BIENESTAR"]),
        "PENDIENTE_FIRMAS": ("PLAN_FIRMAS", "Firmar el plan", resp_firmas or ["BIENESTAR"]),
        "APROBADO": ("PLAN_APROBADO", "Generar la matriz de responsabilidades (F7) e iniciar la implementación", ["BIENESTAR"]),
    }
    if pe in por_estado:
        c, t, r = por_estado[pe]
        out.append(_p(c, t, f"El plan está en {pe}.", "plan", r, "ALTA", plan_id=pid))
    if pe in ("IMPLEMENTACION", "SEGUIMIENTO"):
        for reg in h["rojos"]:
            out.append(_p("REDISENO_PENDIENTE", "Registrar el rediseño de un ajuste en ROJO", "Bloquea el siguiente corte.",
                          "seguimiento", ["BIENESTAR"], "ALTA", plan_id=pid, ajuste_id=reg.ajuste_id, corte=str(reg.corte)))
        for reg in h["tareas"]:
            t = reg.tarea_concertacion
            out.append(_p("CONCERTACION_PENDIENTE", "Concertar un ajuste en AMARILLO", "Bienestar y el estudiante acuerdan cambios antes del siguiente corte.",
                          "seguimiento", ["BIENESTAR", "ESTUDIANTE"], "ALTA", plan_id=pid, ajuste_id=reg.ajuste_id,
                          corte=str(reg.corte), fecha_limite=t.get("fecha_limite")))
        from app.core.errors import AppError
        from app.services import seguimiento as seg

        cal = None
        try:
            cal = seg.calendario_para(db, plan, est)
        except AppError:
            cal = None
        fechas = seg.fechas_cortes(cal) if cal else {}
        for c in ("C1", "C2", "C3"):
            s = h["segs"].get(c)
            if s is not None and s.cerrado:
                continue
            if s is not None:
                out.append(_p("F8_ABIERTO", f"Completar el seguimiento del corte {c}", "Valorar con semáforo cada ajuste.", "seguimiento",
                              ["BIENESTAR"], "ALTA", plan_id=pid, corte=c))
                if h["percepciones_faltantes"]:
                    out.append(_p("PERCEPCION_PENDIENTE", f"Contar cómo le fue con {h['percepciones_faltantes']} ajuste(s) (corte {c})",
                                  "Su percepción hace parte de la evaluación.", "seguimiento", ["ESTUDIANTE"], "ALTA", plan_id=pid, corte=c))
            elif c in fechas and (fechas[c] - hoy).days <= 7:
                out.append(_p("F8_POR_ABRIR", f"Abrir el seguimiento del corte {c}", f"El corte es el {fechas[c].isoformat()}.", "seguimiento",
                              ["BIENESTAR"], "ALTA" if fechas[c] <= hoy else "MEDIA", plan_id=pid, corte=c, fecha_limite=fechas[c].isoformat()))
            break
    c3 = h["segs"].get("C3")
    ev = h["ev"]
    if c3 is not None and c3.cerrado and ev is None:
        out.append(_p("F9_PENDIENTE", "Evaluar la efectividad del plan (F9)", "Decidir qué ajustes se mantienen, modifican o retiran.", "f9", ["BIENESTAR"], "ALTA", plan_id=pid))
    elif ev is not None and ev.estado != "CERRADA":
        out.append(_p("F9_BORRADOR", "Completar y cerrar el F9", "Faltan decisiones y valoraciones.", "f9", ["BIENESTAR"], "ALTA", plan_id=pid))
    elif ev is not None and ev.estado == "CERRADA":
        nota = h["nota"]
        if nota is None:
            out.append(_p("F10_PENDIENTE", "Preparar el F10 (actualización, trayectoria y notas de continuidad)", "Para el siguiente semestre.", "f10", ["BIENESTAR", "ESTUDIANTE"], plan_id=pid))
        elif str(nota.estado) == EstadoNotaContinuidad.PENDIENTE_APROBACION_ESTUDIANTE:
            out.append(_p("F10_APROBACION", "Aprobar la nota de continuidad", "Solo se comparte si usted la aprueba.", "f10", ["ESTUDIANTE"], plan_id=pid))
    return out


def _vista_pendiente(p: dict, rol: str, est_id: int) -> dict:
    q = {k: v for k, v in p.items() if k != "_clave"}
    q["ruta_frontend"] = ruta_front(rol, p["_clave"], estudiante_id=est_id, plan_id=p.get("plan_id"), ajuste_id=None)
    return q


def pendientes(db: Session, est: Estudiante, rol: Rol | str, *, hoy: date | None = None, hechos: dict | None = None) -> list[dict]:
    """Pendientes del estudiante visibles para `rol`. BIENESTAR ve todos; los demas solo aquellos donde son responsables."""
    rol = str(rol)
    h = hechos or _hechos(db, est)
    brutos = _pendientes_brutos(db, h, hoy or date.today())
    if rol != "BIENESTAR":
        brutos = [p for p in brutos if rol in p["responsables"]]
    return [_vista_pendiente(p, rol, est.id) for p in brutos]


# ============================================================================ ruta
def calcular_ruta(db: Session, est: Estudiante, rol: Rol | str, *, hoy: date | None = None) -> dict:
    """Los 12 pasos (`hecho|actual|pendiente`), los pasos previos (F0, AQ-10) y «lo que sigue» para `rol`."""
    rol = str(rol)
    hoy = hoy or date.today()
    h = _hechos(db, est)
    pasos = _pasos(h)
    ve_aq10 = rol in ("BIENESTAR", "ESTUDIANTE")
    previos = [{"codigo": "F0", "nombre": "Consentimiento informado", "estado": "hecho" if h["consent"] else "actual",
                "ruta_frontend": ruta_front(rol, "consentimiento", estudiante_id=est.id)}]
    if ve_aq10:  # el coordinador no ve nada del AQ-10 (ni siquiera si se aplico)
        previos.append({"codigo": "AQ10", "nombre": "Tamizaje AQ-10", "estado": "hecho" if h["aq10"] else ("actual" if h["consent"] else "pendiente"),
                        "ruta_frontend": ruta_front(rol, "aq10", estudiante_id=est.id)})
    plan = h["plan"]
    for p in pasos:
        p["ruta_frontend"] = ruta_front(rol, p.pop("_clave"), estudiante_id=est.id, plan_id=plan.id if plan else None)
    pend = pendientes(db, est, rol, hoy=hoy, hechos=h)
    actual = next((p for p in pasos if p["estado"] == "actual"), None)
    if pend:
        s = pend[0]
        siguiente = {"titulo": s["titulo"], "descripcion": s["descripcion"], "ruta_frontend": s["ruta_frontend"], "codigo": s["codigo"]}
    elif actual is not None:
        siguiente = {"titulo": f"Estamos trabajando en el paso {actual['numero']}: {actual['nombre']}",
                     "descripcion": "Por ahora no hay nada pendiente de su parte. Le avisaremos cuando haya algo para hacer.",
                     "ruta_frontend": ruta_front(rol, "ruta", estudiante_id=est.id), "codigo": None}
    else:
        siguiente = {"titulo": "Recorrido completo", "descripcion": "Completó los 12 pasos de este semestre.",
                     "ruta_frontend": ruta_front(rol, "ruta", estudiante_id=est.id), "codigo": None}
    return {
        "estudiante_id": est.id,
        "plan": {"id": plan.id, "estado": str(plan.estado), "semaforo": str(plan.semaforo_actual) if plan.semaforo_actual else None,
                 "version": plan.version} if plan else None,
        "previos": previos, "pasos": pasos,
        "progreso": {"hechos": sum(1 for p in pasos if p["estado"] == "hecho"), "total": 12},
        "paso_actual": actual["numero"] if actual else None,
        "siguiente": siguiente, "pendientes": len(pend),
        **({"ruta_activada": h["aq10_activa_ruta"]} if ve_aq10 and h["aq10"] else {}),
    }


def resumen_tablero(db: Session, est: Estudiante, user: Usuario, rol: Rol | str, *, hoy: date | None = None) -> dict:
    """Fila del tablero. NUNCA incluye AQ-10 ni datos clinicos (tampoco `siguiente`: ver /estudiantes/{id}/pendientes)."""
    from app.models.academico import ProgramaAcademico

    r = calcular_ruta(db, est, rol, hoy=hoy)
    prog = db.get(ProgramaAcademico, est.programa_id) if est.programa_id else None
    b = db.get(Usuario, est.bienestar_asignado_id) if est.bienestar_asignado_id else None
    plan = r["plan"]
    return {
        "id": est.id, "usuario_id": user.id, "nombre_completo": user.nombre_completo, "codigo_estudiante": est.codigo_estudiante,
        "programa_id": est.programa_id, "programa": prog.nombre_programa if prog else None,
        "semestre_actual": est.semestre_actual, "estado_cuenta": str(user.estado), "estado_academico": str(est.estado_academico),
        "via_ingreso": str(est.via_ingreso),
        "bienestar_asignado": {"id": b.id, "nombre_completo": b.nombre_completo} if b else None,
        "plan": plan, "semaforo_agregado": plan["semaforo"] if plan else None,
        "paso_actual": r["paso_actual"], "progreso": r["progreso"], "pendientes": r["pendientes"],
    }


__all__ = ["PASOS", "calcular_ruta", "pendientes", "plan_vigente_de", "resumen_tablero", "ruta_front"]
