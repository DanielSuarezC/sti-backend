"""Logica del semaforo F8 (arquitectura v7 §7.2, RF-29, RF-39, D11). La logica vive SOLO aqui (P6).

Reglas (documentadas tambien en docs/api/slice_c2.md):

* VERDE     El ajuste responde a la barrera. Se mantiene y queda registrado como EFECTIVO (``estado_seguimiento == "EFECTIVO"``);
            esa lectura alimenta la trayectoria (M8), el F9 y el motor CBR al cerrar el F9.
* AMARILLO  Efectividad parcial. Se crea una TAREA DE CONCERTACION entre Bienestar y el estudiante con fecha limite = el
            siguiente corte (en C3: fin del semestre). La tarea es un JSON ``tarea_concertacion`` en el registro del ajuste
            + una NOTIFICACION ``tipo="TAREA_CONCERTACION"`` para Bienestar y el estudiante. Se cierra con
            ``resolver_concertacion`` (acuerdo escrito) o automaticamente si el semaforo pasa a VERDE.
* ROJO      Notificacion INMEDIATA (push + correo) a exactamente 4 actores (RF-39 / D11): el profesional de Bienestar
            responsable del estudiante, el Coordinador del programa, el Docente responsable del ajuste y el Estudiante.
            El ajuste queda ``REQUIERE_REDISENO`` (``estado_seguimiento``) y BLOQUEA abrir el siguiente corte hasta
            registrar el rediseno (``registrar_rediseno``). En C2 el rediseno es obligatorio (v7 §7.2); la misma regla
            se aplica a C1 y, en C3, el F9 no admite ``MANTENER`` para un ajuste cuyo ultimo semaforo es ROJO.
            Dedupe: una notificacion por (registro de ajuste, usuario) -> reenviar el mismo semaforo no duplica.

Cada cambio de semaforo se audita (``CAMBIO_SEMAFORO``: de -> a, quien, ajuste, corte).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict
from app.models.academico import AsignacionDocente
from app.models.base import utcnow
from app.models.enums import Corte, EstadoAjuste, EstadoUsuario, Rol, Semaforo
from app.models.plan import AjusteRazonable, PlanMaarTea
from app.models.seguimiento import RegistroSeguimientoAjuste, Seguimiento
from app.models.usuarios import CoordinadorPrograma, Docente, Estudiante, Usuario
from app.services.notifications import Evento, notify
from app.services.ruta import ruta_front

RANGO: dict[str, int] = {"VERDE": 0, "AMARILLO": 1, "ROJO": 2}
ORDEN_CORTES: tuple[str, ...] = ("C1", "C2", "C3")


def rank(s: Any) -> int | None:
    return None if s is None else RANGO[str(s)]


def peor(valores) -> str | None:
    """El peor semaforo de una coleccion (ignora None). ROJO > AMARILLO > VERDE."""
    validos = [str(v) for v in valores if v is not None]
    return max(validos, key=lambda x: RANGO[x]) if validos else None


def corte_anterior(corte: Any) -> str | None:
    i = ORDEN_CORTES.index(str(corte))
    return ORDEN_CORTES[i - 1] if i > 0 else None


def corte_siguiente(corte: Any) -> str | None:
    i = ORDEN_CORTES.index(str(corte))
    return ORDEN_CORTES[i + 1] if i < len(ORDEN_CORTES) - 1 else None


def estado_seguimiento(reg: RegistroSeguimientoAjuste | None) -> str | None:
    """Estado derivado del ajuste en el corte: EFECTIVO | CONCERTACION_ABIERTA | CONCERTACION_RESUELTA |
    REQUIERE_REDISENO | REDISENO_REGISTRADO | None (sin valorar)."""
    if reg is None or reg.semaforo is None:
        return None
    s = str(reg.semaforo)
    if s == "VERDE":
        return "EFECTIVO"
    if s == "AMARILLO":
        t = reg.tarea_concertacion or {}
        return "CONCERTACION_RESUELTA" if t.get("estado") == "RESUELTA" else "CONCERTACION_ABIERTA"
    return "REDISENO_REGISTRADO" if reg.rediseno else "REQUIERE_REDISENO"


# ============================================================================ destinatarios
def _usuario_activo(db: Session, usuario_id: int | None) -> Usuario | None:
    if not usuario_id:
        return None
    u = db.get(Usuario, usuario_id)
    return u if u is not None and str(u.estado) == EstadoUsuario.ACTIVO else None


def coordinadores_del_programa(db: Session, programa_id: int | None) -> list[Usuario]:
    """Coordinador(es) ACTIVOS del programa (lista en COORDINADOR_PROGRAMA o nombrado en el programa)."""
    if programa_id is None:
        return []
    from app.models.academico import ProgramaAcademico

    ids: list[int] = []
    prog = db.get(ProgramaAcademico, programa_id)
    if prog is not None and prog.coordinador_programa_id:
        c = db.get(CoordinadorPrograma, prog.coordinador_programa_id)
        if c is not None:
            ids.append(c.usuario_id)
    for c in db.scalars(select(CoordinadorPrograma)):
        if programa_id in [int(x) for x in (c.programa_responsable_ids or [])] and c.usuario_id not in ids:
            ids.append(c.usuario_id)
    out = [u for u in (_usuario_activo(db, i) for i in ids) if u is not None and str(u.rol) == Rol.COORDINADOR]
    return out


def docentes_responsables(db: Session, ajuste: AjusteRazonable, semestre: str | None = None) -> list[Usuario]:
    """Docente responsable del ajuste: `responsable_id`; si no hay, los docentes asignados a la asignatura del ajuste."""
    u = _usuario_activo(db, ajuste.responsable_id)
    if u is not None:
        return [u]
    if not ajuste.asignatura_id:
        return []
    stmt = (
        select(Docente.usuario_id)
        .join(AsignacionDocente, AsignacionDocente.docente_id == Docente.id)
        .where(AsignacionDocente.asignatura_id == ajuste.asignatura_id, AsignacionDocente.deleted_at.is_(None))
    )
    if semestre:
        stmt = stmt.where(AsignacionDocente.semestre_academico == semestre)
    users = [_usuario_activo(db, i) for i in dict.fromkeys(db.scalars(stmt))]
    return [x for x in users if x is not None]


def bienestar_responsable(db: Session, est: Estudiante, plan: PlanMaarTea | None, actor: Usuario | None) -> Usuario | None:
    """Profesional de Bienestar del estudiante: asignado -> elaborador del plan -> quien actua (si es Bienestar)."""
    candidatos: list[int | None] = [est.bienestar_asignado_id]
    if plan is not None:
        candidatos.append(plan.elaborado_por_id)
        candidatos.extend(plan.profesionales_responsables_ids or [])
    for cid in candidatos:
        u = _usuario_activo(db, cid)
        if u is not None and str(u.rol) == Rol.BIENESTAR:
            return u
    if actor is not None and str(actor.rol) == Rol.BIENESTAR:
        return actor
    return None


def destinatarios_rojo(db: Session, est: Estudiante, plan: PlanMaarTea, ajuste: AjusteRazonable,
                       actor: Usuario | None) -> dict[str, list[Usuario]]:
    """Los 4 actores de RF-39 / D11 (cada rol puede quedar vacio si no hay una persona activa que lo ocupe)."""
    b = bienestar_responsable(db, est, plan, actor)
    est_user = _usuario_activo(db, est.usuario_id)
    return {
        "BIENESTAR": [b] if b else [],
        "COORDINADOR": coordinadores_del_programa(db, est.programa_id),
        "DOCENTE": docentes_responsables(db, ajuste, plan.semestre_academico),
        "ESTUDIANTE": [est_user] if est_user else [],
    }


# ============================================================================ aplicar semaforo
def aplicar_semaforo(
    db: Session, *, registro: RegistroSeguimientoAjuste, ajuste: AjusteRazonable, plan: PlanMaarTea, est: Estudiante,
    nuevo: Semaforo | str | None, actor: Usuario, fecha_limite: date | None = None, request=None,
) -> dict:
    """Fija el semaforo del registro y dispara la regla correspondiente. Devuelve un resumen para la respuesta.

    No hace commit. Reenviar el mismo valor no cambia nada (ni audita ni notifica).
    """
    res: dict[str, Any] = {
        "cambio": False, "anterior": str(registro.semaforo) if registro.semaforo else None,
        "nuevo": str(registro.semaforo) if registro.semaforo else None,
        "notificados": [], "tarea_concertacion": None, "requiere_rediseno": False,
    }
    if nuevo is None or (registro.semaforo is not None and str(registro.semaforo) == str(nuevo)):
        return res
    nuevo_s = str(nuevo)
    anterior = res["anterior"]
    registro.semaforo = Semaforo(nuevo_s)
    registro.semaforo_cambiado_at = utcnow()
    res.update(cambio=True, nuevo=nuevo_s)
    audit.log(
        db, actor, audit.Accion.CAMBIO_SEMAFORO, "registro_seguimiento_ajuste", registro.id,
        {"de": anterior, "a": nuevo_s, "ajuste_id": ajuste.id, "plan_id": plan.id, "corte": str(registro.corte)},
        request=request, estudiante_id=est.id,
    )
    # Si salia de AMARILLO con tarea abierta y ya no es AMARILLO: se cancela.
    t = registro.tarea_concertacion
    if anterior == "AMARILLO" and nuevo_s != "AMARILLO" and t and t.get("estado") == "ABIERTA":
        registro.tarea_concertacion = {**t, "estado": "CANCELADA", "cancelada_at": utcnow().isoformat(),
                                       "motivo": f"El semáforo cambió a {nuevo_s}."}
    if nuevo_s == "AMARILLO":
        _crear_tarea_concertacion(db, registro, ajuste, plan, est, actor, fecha_limite, res)
    elif nuevo_s == "ROJO":
        _alerta_roja(db, registro, ajuste, plan, est, actor, res)
    db.flush()
    recalcular_caches(db, plan)
    return res


def _crear_tarea_concertacion(db, registro, ajuste, plan, est, actor, fecha_limite, res) -> None:
    ahora = utcnow().isoformat()
    registro.tarea_concertacion = {
        "estado": "ABIERTA", "corte_origen": str(registro.corte),
        "fecha_limite": fecha_limite.isoformat() if fecha_limite else None,
        "asignada_a": ["BIENESTAR", "ESTUDIANTE"], "creada_at": ahora, "acuerdo": None, "resuelta_at": None,
    }
    res["tarea_concertacion"] = registro.tarea_concertacion
    b = bienestar_responsable(db, est, plan, actor)
    est_user = _usuario_activo(db, est.usuario_id)
    base = {
        "ajuste": ajuste.nombre_ajuste, "corte": str(registro.corte), "plan_id": plan.id, "ajuste_id": ajuste.id,
        "registro_id": registro.id, "fecha_limite": fecha_limite.isoformat() if fecha_limite else None,
    }
    key = f"semaforo-amarillo:{registro.id}"
    for rol, user in (("BIENESTAR", b), ("ESTUDIANTE", est_user)):
        if user is None:
            continue
        pl = {**base, "enlace": ruta_front(rol, "seguimiento", estudiante_id=est.id, plan_id=plan.id, ajuste_id=ajuste.id)}
        for n in notify(db, Evento.AJUSTE_SEMAFORO_AMARILLO, [user], pl, dedupe_key=key):
            n.tipo = "TAREA_CONCERTACION"  # tarea persistente visible en "pendientes" (ver services/ruta.py)
        res["notificados"].append(rol)


def _alerta_roja(db, registro, ajuste, plan, est, actor, res) -> None:
    res["requiere_rediseno"] = registro.rediseno is None
    base = {"ajuste": ajuste.nombre_ajuste, "corte": str(registro.corte), "plan_id": plan.id, "ajuste_id": ajuste.id,
            "registro_id": registro.id}
    key = f"semaforo-rojo:{registro.id}"
    for rol, users in destinatarios_rojo(db, est, plan, ajuste, actor).items():
        if not users:
            continue
        pl = {**base, "enlace": ruta_front(rol, "seguimiento", estudiante_id=est.id, plan_id=plan.id, ajuste_id=ajuste.id)}
        notify(db, Evento.AJUSTE_SEMAFORO_ROJO, list(users), pl, dedupe_key=key)  # push + correo (catalogo M10)
        res["notificados"].append(rol)


# ============================================================================ concertacion / rediseno
def resolver_concertacion(db: Session, registro: RegistroSeguimientoAjuste, actor: Usuario, acuerdo: str,
                          est: Estudiante, request=None) -> dict:
    t = registro.tarea_concertacion
    if not t or str(registro.semaforo) != "AMARILLO":
        raise Conflict("Este ajuste no tiene una tarea de concertación pendiente (solo los ajustes en AMARILLO la tienen).",
                       "SIN_TAREA_CONCERTACION")
    if t.get("estado") == "RESUELTA":
        raise Conflict("La tarea de concertación ya fue resuelta.", "CONCERTACION_YA_RESUELTA")
    registro.tarea_concertacion = {**t, "estado": "RESUELTA", "acuerdo": acuerdo, "resuelta_at": utcnow().isoformat(),
                                   "resuelta_por_id": actor.id}
    audit.log(db, actor, "CONCERTACION_RESUELTA", "registro_seguimiento_ajuste", registro.id,
              {"ajuste_id": registro.ajuste_id, "corte": str(registro.corte)}, request=request, estudiante_id=est.id)
    db.flush()
    return registro.tarea_concertacion


def registrar_rediseno(db: Session, registro: RegistroSeguimientoAjuste, actor: Usuario, est: Estudiante, *,
                       decision: str, descripcion: str, concertado_con_estudiante: bool,
                       nueva_version_plan: int | None, request=None) -> dict:
    if registro.semaforo is None or str(registro.semaforo) != "ROJO":
        raise Conflict("Solo se registra rediseño para ajustes en ROJO.", "AJUSTE_NO_ESTA_EN_ROJO")
    registro.rediseno = {
        "decision": decision, "descripcion": descripcion, "concertado_con_estudiante": concertado_con_estudiante,
        "nueva_version_plan": nueva_version_plan, "registrado_at": utcnow().isoformat(), "registrado_por_id": actor.id,
    }
    audit.log(db, actor, "REDISENO_REGISTRADO", "registro_seguimiento_ajuste", registro.id,
              {"ajuste_id": registro.ajuste_id, "corte": str(registro.corte), "decision": decision},
              request=request, estudiante_id=est.id)
    db.flush()
    return registro.rediseno


def registros_del_plan(db: Session, plan_id: int) -> list[tuple[RegistroSeguimientoAjuste, str]]:
    rows = db.execute(
        select(RegistroSeguimientoAjuste, Seguimiento.corte)
        .join(Seguimiento, Seguimiento.id == RegistroSeguimientoAjuste.seguimiento_id)
        .where(Seguimiento.plan_id == plan_id, Seguimiento.deleted_at.is_(None))
        .order_by(Seguimiento.corte, RegistroSeguimientoAjuste.ajuste_id)
    ).all()
    return [(r, str(c)) for r, c in rows]


def rojos_sin_rediseno(db: Session, plan_id: int, antes_de: Corte | str | None = None) -> list[RegistroSeguimientoAjuste]:
    """Registros ROJO sin rediseno registrado (si `antes_de`, solo de cortes anteriores a ese corte)."""
    out = []
    for reg, corte in registros_del_plan(db, plan_id):
        if antes_de is not None and ORDEN_CORTES.index(corte) >= ORDEN_CORTES.index(str(antes_de)):
            continue
        if reg.semaforo is not None and str(reg.semaforo) == "ROJO" and not reg.rediseno:
            out.append(reg)
    return out


# ============================================================================ caches y matriz
def ajustes_activos(db: Session, plan_id: int, ajuste_ids: set[int] | None = None) -> list[AjusteRazonable]:
    stmt = select(AjusteRazonable).where(
        AjusteRazonable.plan_id == plan_id, AjusteRazonable.estado != EstadoAjuste.RETIRADO
    ).order_by(AjusteRazonable.id)
    ajustes = list(db.scalars(stmt))
    if ajuste_ids is not None:
        ajustes = [a for a in ajustes if a.id in ajuste_ids]
    return ajustes


def recalcular_caches(db: Session, plan: PlanMaarTea) -> str | None:
    """`ajuste.semaforo_actual` = ultimo semaforo valorado del ajuste; `plan.semaforo_actual` = el peor de los ajustes;
    `seguimiento.semaforo_estado` = el peor del corte. Devuelve el semaforo agregado del plan."""
    db.flush()
    por_ajuste: dict[int, tuple[int, str]] = {}
    por_corte: dict[int, list[str]] = {}
    for reg, corte in registros_del_plan(db, plan.id):
        if reg.semaforo is None:
            continue
        por_corte.setdefault(reg.seguimiento_id, []).append(str(reg.semaforo))
        i = ORDEN_CORTES.index(corte)
        if reg.ajuste_id not in por_ajuste or por_ajuste[reg.ajuste_id][0] <= i:
            por_ajuste[reg.ajuste_id] = (i, str(reg.semaforo))
    for a in ajustes_activos(db, plan.id):
        a.semaforo_actual = Semaforo(por_ajuste[a.id][1]) if a.id in por_ajuste else None
    for seg_id, vals in por_corte.items():
        seg = db.get(Seguimiento, seg_id)
        if seg is not None:
            seg.semaforo_estado = Semaforo(peor(vals))
    agregado = peor(v for _, v in por_ajuste.values())
    plan.semaforo_actual = Semaforo(agregado) if agregado else None
    db.flush()
    return agregado


def tendencia_de(valores: list[str | None]) -> str:
    """MEJORA | EMPEORA | ESTABLE | SIN_DATOS segun los dos ultimos semaforos valorados (C1->C2->C3)."""
    v = [x for x in valores if x is not None]
    if len(v) < 2:
        return "SIN_DATOS"
    a, b = RANGO[v[-2]], RANGO[v[-1]]
    return "MEJORA" if b < a else "EMPEORA" if b > a else "ESTABLE"


def serializar_registro(reg: RegistroSeguimientoAjuste, *, vista: str = "completa") -> dict:
    """`vista="docente"`: solo lo que el docente puede ver (semaforo, implementacion, su comentario)."""
    base = {
        "id": reg.id, "seguimiento_id": reg.seguimiento_id, "ajuste_id": reg.ajuste_id, "corte": str(reg.corte),
        "semaforo": str(reg.semaforo) if reg.semaforo else None, "estado_seguimiento": estado_seguimiento(reg),
        "implementado": reg.implementado, "frecuencia_implementacion": reg.frecuencia_implementacion,
        "comentario_docente": reg.comentario_docente,
        "semaforo_cambiado_at": reg.semaforo_cambiado_at.isoformat() if reg.semaforo_cambiado_at else None,
    }
    if vista == "docente":
        return base
    base.update(
        resultado_observado=reg.resultado_observado,
        percepcion_estudiante=str(reg.percepcion_estudiante) if reg.percepcion_estudiante else None,
        comentario_estudiante=reg.comentario_estudiante,
        nueva_barrera_detectada=reg.nueva_barrera_detectada,
        tarea_concertacion=reg.tarea_concertacion, rediseno=reg.rediseno,
    )
    return base


def construir_matriz(db: Session, plan: PlanMaarTea, ajuste_ids: set[int] | None = None, *, vista: str = "completa") -> dict:
    """Matriz ajuste x corte + tendencia + resumen (% verde). `ajuste_ids` filtra (docente: solo sus ajustes)."""
    ajustes = ajustes_activos(db, plan.id, ajuste_ids)
    ids = {a.id for a in ajustes}
    regs: dict[tuple[int, str], RegistroSeguimientoAjuste] = {}
    for reg, corte in registros_del_plan(db, plan.id):
        if reg.ajuste_id in ids:
            regs[(reg.ajuste_id, corte)] = reg
    filas = []
    for a in ajustes:
        por_corte = {c: (serializar_registro(regs[(a.id, c)], vista=vista) if (a.id, c) in regs else None) for c in ORDEN_CORTES}
        sems = [por_corte[c]["semaforo"] if por_corte[c] else None for c in ORDEN_CORTES]
        ultimo = next((regs[(a.id, c)] for c in reversed(ORDEN_CORTES) if (a.id, c) in regs and regs[(a.id, c)].semaforo), None)
        filas.append({
            "ajuste_id": a.id, "nombre_ajuste": a.nombre_ajuste, "tipo_ajuste": str(a.tipo_ajuste),
            "asignatura_id": a.asignatura_id, "responsable_id": a.responsable_id,
            "semaforo_actual": next((s for s in reversed(sems) if s), None), "tendencia": tendencia_de(sems),
            "estado_seguimiento": estado_seguimiento(ultimo), "cortes": por_corte,
        })
    total = len(filas)
    por_corte_res: dict[str, dict] = {}
    for c in ORDEN_CORTES:
        cnt = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0}
        for f in filas:
            r = f["cortes"][c]
            if r and r["semaforo"]:
                cnt[r["semaforo"]] += 1
        valorados = sum(cnt.values())
        por_corte_res[c] = {**cnt, "SIN_VALORAR": total - valorados, "total": total, "valorados": valorados,
                            "porcentaje_verde": round(100 * cnt["VERDE"] / total, 1) if total else None}
    actuales = [f["semaforo_actual"] for f in filas]
    verdes_actual = sum(1 for s in actuales if s == "VERDE")
    return {
        "plan_id": plan.id, "cortes": list(ORDEN_CORTES), "ajustes": filas,
        "resumen": {
            "por_corte": por_corte_res, "semaforo_agregado": peor(actuales),
            "porcentaje_verde_actual": round(100 * verdes_actual / total, 1) if total else None,
            "total_ajustes": total,
            "ajustes_efectivos": [f["ajuste_id"] for f in filas if f["semaforo_actual"] == "VERDE"],
            "requieren_rediseno": [f["ajuste_id"] for f in filas if f["estado_seguimiento"] == "REQUIERE_REDISENO"],
        },
    }
