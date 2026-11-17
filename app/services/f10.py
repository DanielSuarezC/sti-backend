"""F10 (RF-34/35, HU-17, D8): actualizacion del plan, trayectoria y notas de continuidad.

Puntos de integracion para otros slices:
* ``contexto_para_f3(db, estudiante_id, semestre)``  -> contexto inicial del F3 (slice B) o ``None`` si no hay F10 aprobado.
* ``estudiantes_en_practicas(db, semestre, anticipacion=0)`` y ``notificar_semestre_practicas(db, semestre)`` -> job diario (slice A).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.models.academico import CalendarioAcademico, ProgramaAcademico
from app.models.base import utcnow
from app.models.enums import (
    EstadoAjuste,
    EstadoImplementacionDua,
    EstadoNotaContinuidad,
    EstadoPlanEnum,
    EstadoUsuario,
    Rol,
    TipoHito,
)
from app.models.evaluacion import DecisionPlan, EvaluacionPlan, NotaContinuidad
from app.models.f10 import EstadoF10, F10Semestre
from app.models.plan import (
    AjusteRazonable,
    EstrategiaDua,
    PlanMaarTea,
    RespuestaAmbiente,
    RespuestaComunicacion,
    RespuestaEvaluacion,
    RespuestaInteraccion,
    RespuestaPedagogia,
    RespuestaTecnologia,
)
from app.models.trayectoria import HitoTrayectoria
from app.models.usuarios import Estudiante, Usuario
from app.services import trayectoria as svc_tray
from app.services.notifications import Evento, get_notification_user_ids, notify

N = EstadoNotaContinuidad
_RESPUESTAS = (RespuestaAmbiente, RespuestaComunicacion, RespuestaEvaluacion, RespuestaInteraccion,
               RespuestaPedagogia, RespuestaTecnologia)


# ============================================================================ consulta
def get_f10_or_404(db: Session, estudiante_id: int, f10_id: int) -> F10Semestre:
    f = db.get(F10Semestre, f10_id)
    if f is None or f.estudiante_id != estudiante_id:
        raise NotFound("No encontramos ese F10 para este estudiante.", "F10_NO_ENCONTRADO")
    return f


def listar_f10(db: Session, estudiante_id: int) -> list[F10Semestre]:
    return list(db.scalars(select(F10Semestre).where(F10Semestre.estudiante_id == estudiante_id)
                           .order_by(F10Semestre.semestre_origen.desc())))


def _nombre(db: Session, usuario_id: int | None) -> str | None:
    u = db.get(Usuario, usuario_id) if usuario_id else None
    return u.nombre_completo if u else None


def serializar_resumen(db: Session, f: F10Semestre) -> dict[str, Any]:
    return {
        "id": f.id, "estudiante_id": f.estudiante_id, "semestre_origen": f.semestre_origen,
        "semestre_destino": f.semestre_destino, "estado": str(f.estado), "plan_id": f.plan_id,
        "evaluacion_id": f.evaluacion_id, "trayectoria_id": f.trayectoria_id, "plan_siguiente_id": f.plan_siguiente_id,
        "generado_at": f.generado_at,
        "aprobacion_bienestar": {"usuario_id": f.aprobado_bienestar_por_id,
                                 "nombre": _nombre(db, f.aprobado_bienestar_por_id),
                                 "aprobado_at": f.aprobado_bienestar_at},
        "aprobacion_estudiante": {"usuario_id": f.aprobado_estudiante_por_id,
                                  "nombre": _nombre(db, f.aprobado_estudiante_por_id),
                                  "aprobado_at": f.aprobado_estudiante_at},
        "aprobado_at": f.aprobado_at,
    }


def componente_trayectoria(db: Session, f: F10Semestre) -> dict[str, Any] | None:
    tray = db.get(svc_tray.TrayectoriaAcademica, f.trayectoria_id) if f.trayectoria_id else None
    if tray is None:
        return None
    est = db.get(Estudiante, f.estudiante_id)
    out = svc_tray.serializar_trayectoria(tray)
    out["resumen"] = svc_tray.resumen_trayectoria(db, est)
    out["hitos"] = svc_tray.listar_hitos(db, f.estudiante_id)
    return out


def serializar_f10(db: Session, f: F10Semestre, user: Usuario, advertencias: list[str] | None = None) -> dict[str, Any]:
    out = serializar_resumen(db, f)
    out.update({
        "comentario_estudiante": f.comentario_estudiante,
        "actualizacion_plan": f.actualizacion_plan or {"items": []},
        "trayectoria": componente_trayectoria(db, f),
        "necesidades_anticipadas": f.necesidades_anticipadas or [],
        "proyeccion": f.proyeccion,
        "notas": [serializar_nota(db, n, user) for n in notas_visibles(db, f, user)],
        "advertencias": advertencias or [],
    })
    return out


# ============================================================================ borrador
def _plan_de_semestre(db: Session, estudiante_id: int, semestre: str) -> PlanMaarTea | None:
    return db.scalar(select(PlanMaarTea).where(
        PlanMaarTea.estudiante_id == estudiante_id, PlanMaarTea.semestre_academico == semestre,
        PlanMaarTea.estado != EstadoPlanEnum.ARCHIVADO))


def _items_desde_plan(db: Session, plan: PlanMaarTea | None) -> tuple[list[dict], EvaluacionPlan | None]:
    if plan is None:
        return [], None
    ev = db.scalar(select(EvaluacionPlan).where(EvaluacionPlan.plan_id == plan.id).order_by(EvaluacionPlan.id.desc()))
    decisiones: dict[tuple[str, int | None], DecisionPlan] = {}
    nuevos: list[DecisionPlan] = []
    if ev is not None:
        for d in db.scalars(select(DecisionPlan).where(DecisionPlan.evaluacion_id == ev.id).order_by(DecisionPlan.id)):
            if str(d.estado_decision) == "CANCELADA":
                continue
            if str(d.tipo_decision) == "CREAR_NUEVO":
                nuevos.append(d)
            else:
                decisiones[(str(d.elemento_afectado), d.elemento_id)] = d
    items: list[dict] = []

    def _item(elemento: str, obj, nombre: str, descripcion: str, semaforo) -> dict:
        d = decisiones.get((elemento, obj.id))
        tipo = str(d.tipo_decision) if d else "MANTENER"
        return {
            "elemento": elemento, "elemento_id": obj.id, "nombre": nombre,
            "tipo_decision": tipo if tipo in ("MANTENER", "MODIFICAR", "RETIRAR") else "MANTENER",
            "origen_decision": "F9" if d else "SIN_DECISION_F9", "decision_id": d.id if d else None,
            "descripcion_cambio": d.descripcion_decision if d and tipo == "MODIFICAR" else None,
            "justificacion": d.justificacion_decision if d else None,
            "descripcion_actual": descripcion, "semaforo": str(semaforo) if semaforo else None,
        }

    for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id)):
        if str(a.estado) != EstadoAjuste.RETIRADO:
            items.append(_item("AJUSTE", a, a.nombre_ajuste, a.descripcion_ajuste, a.semaforo_actual))
    for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id).order_by(EstrategiaDua.id)):
        items.append(_item("ESTRATEGIA", e, e.nombre_estrategia, e.descripcion, None))
    for (elemento, eid), d in decisiones.items():  # decisiones sobre apoyos / plan completo: informativas
        if elemento in ("APOYO", "PLAN_COMPLETO"):
            items.append({"elemento": elemento, "elemento_id": eid, "nombre": d.descripcion_decision[:120],
                          "tipo_decision": str(d.tipo_decision), "origen_decision": "F9", "decision_id": d.id,
                          "descripcion_cambio": None, "justificacion": d.justificacion_decision,
                          "descripcion_actual": None, "semaforo": None, "informativo": True})
    for d in nuevos:
        items.append({"elemento": "NUEVO", "elemento_id": None, "nombre": d.descripcion_decision[:120],
                      "tipo_decision": "CREAR_NUEVO", "origen_decision": "F9", "decision_id": d.id,
                      "descripcion_cambio": d.descripcion_decision, "justificacion": d.justificacion_decision,
                      "descripcion_actual": None, "semaforo": None, "informativo": True})
    return items, ev


def _semestre_origen_por_defecto(db: Session, estudiante_id: int) -> str | None:
    planes = [p.semestre_academico for p in db.scalars(
        select(PlanMaarTea).where(PlanMaarTea.estudiante_id == estudiante_id, PlanMaarTea.estado != EstadoPlanEnum.ARCHIVADO))]
    if planes:
        return max(planes)
    trays = svc_tray.listar_trayectorias(db, estudiante_id)
    return trays[-1].semestre_academico if trays else None


def _necesidades_desde_proyeccion(nec: dict[str, Any], semestre_destino: str) -> list[dict[str, Any]]:
    return [{"tipo": n["tipo"], "semestre_estimado": semestre_destino, "descripcion": n["descripcion"],
             "apoyos_previstos": None, "origen": "PROYECCION"} for n in nec.get("necesidades", [])]


def generar_borrador(db: Session, est: Estudiante, actor: Usuario, semestre_origen: str | None = None,
                     semestre_destino: str | None = None) -> F10Semestre:
    """Borrador del F10 desde el F9 (decisiones por ajuste) y el historial (trayectorias previas, hitos, plan de estudios)."""
    origen = semestre_origen or _semestre_origen_por_defecto(db, est.id)
    if origen is None:
        raise Unprocessable("No hay plan ni trayectoria previos: indique el semestre que se cierra (semestre_origen).",
                            "SEMESTRE_ORIGEN_REQUERIDO")
    destino = semestre_destino or svc_tray.siguiente_semestre(origen)
    if destino <= origen:
        raise Unprocessable("El semestre destino debe ser posterior al semestre que se cierra.", "SEMESTRES_INVALIDOS")
    existente = db.scalar(select(F10Semestre).where(F10Semestre.estudiante_id == est.id, F10Semestre.semestre_origen == origen))
    if existente is not None:
        raise Conflict(f"Ya existe el F10 del semestre {origen} (id {existente.id}). Edítelo en lugar de generar otro.",
                       "F10_YA_EXISTE", extra={"f10_id": existente.id})
    plan = _plan_de_semestre(db, est.id, origen)
    items, ev = _items_desde_plan(db, plan)
    anteriores = [t for t in svc_tray.listar_trayectorias(db, est.id) if t.semestre_academico < origen]
    tray = svc_tray.get_trayectoria(db, est.id, origen) or svc_tray.crear_borrador_trayectoria(db, est, origen, anteriores)
    nivel_destino = (est.semestre_actual or len(anteriores) + 1) + 1
    nec = svc_tray.proyectar_necesidades(db, est, nivel_destino)
    proy = {"graduacion": svc_tray.proyeccion_graduacion(db, est), "siguiente_semestre": nec}
    f = F10Semestre(
        estudiante_id=est.id, semestre_origen=origen, semestre_destino=destino, estado=EstadoF10.BORRADOR,
        plan_id=plan.id if plan else None, evaluacion_id=ev.id if ev else None, trayectoria_id=tray.id,
        actualizacion_plan={"items": items, "nuevos_propuestos": [], "observaciones": None},
        necesidades_anticipadas=_necesidades_desde_proyeccion(nec, destino), proyeccion=proy,
        generado_at=utcnow(), elaborado_por_id=actor.id,
    )
    db.add(f)
    db.flush()
    audit.log(db, actor, "F10_BORRADOR_GENERADO", "f10_semestre", f.id,
              {"semestre_origen": origen, "semestre_destino": destino, "con_f9": ev is not None}, estudiante_id=est.id)
    return f


# ============================================================================ edicion de componentes
def _assert_editable(f: F10Semestre) -> list[str]:
    """Devuelve advertencias; si habia una aprobacion, la invalida (lo aprobado debe ser lo que se reviso)."""
    if f.estado == EstadoF10.APROBADO:
        raise Conflict("Este F10 ya fue aprobado por Bienestar y el estudiante; no se puede modificar.",
                       "F10_APROBADO_INMUTABLE")
    adv: list[str] = []
    if f.estado == EstadoF10.PENDIENTE_APROBACION:
        f.aprobado_bienestar_por_id = f.aprobado_bienestar_at = None
        f.aprobado_estudiante_por_id = f.aprobado_estudiante_at = None
        f.estado = EstadoF10.BORRADOR
        adv.append("El cambio anuló la aprobación que ya se había registrado: ambos deben volver a aprobar el F10.")
    return adv


def actualizar_plan(db: Session, f: F10Semestre, body, actor: Usuario) -> list[str]:
    adv = _assert_editable(f)
    actual = dict(f.actualizacion_plan or {"items": []})
    items = {(i["elemento"], i["elemento_id"]): dict(i) for i in actual.get("items", [])}
    if body.items:
        for it in body.items:
            clave = (it.elemento, it.elemento_id)
            if clave not in items or items[clave].get("informativo"):
                raise Unprocessable(
                    f"El {it.elemento.lower()} {it.elemento_id} no pertenece al plan del semestre {f.semestre_origen}.",
                    "ELEMENTO_NO_PERTENECE_AL_PLAN")
            items[clave].update({
                "tipo_decision": it.tipo_decision, "origen_decision": "BIENESTAR",
                "descripcion_cambio": it.descripcion_cambio if it.tipo_decision == "MODIFICAR" else None,
                "justificacion": it.justificacion if it.justificacion is not None else items[clave].get("justificacion"),
            })
    actual["items"] = list(items.values())
    if body.nuevos_propuestos is not None:
        actual["nuevos_propuestos"] = [t.strip() for t in body.nuevos_propuestos if t.strip()]
    if body.observaciones is not None:
        actual["observaciones"] = body.observaciones
    f.actualizacion_plan = actual
    db.flush()
    audit.log(db, actor, "F10_PLAN_ACTUALIZADO", "f10_semestre", f.id, {"items": len(actual["items"])},
              estudiante_id=f.estudiante_id)
    return adv


def actualizar_trayectoria_f10(db: Session, f: F10Semestre, est: Estudiante, body, actor: Usuario) -> list[str]:
    adv = _assert_editable(f)
    if f.trayectoria_id is None:
        raise Conflict("Este F10 no tiene trayectoria asociada.", "F10_SIN_TRAYECTORIA")
    tray = db.get(svc_tray.TrayectoriaAcademica, f.trayectoria_id)
    if body.trayectoria is not None:
        svc_tray.actualizar_trayectoria(db, tray, body.trayectoria)
    if body.necesidades_anticipadas is not None:
        f.necesidades_anticipadas = [
            {**n.model_dump(), "origen": "MANUAL"} for n in body.necesidades_anticipadas
        ]
    if body.proyeccion is not None:
        f.proyeccion = {**(f.proyeccion or {}), "ajuste_manual": body.proyeccion}
    db.flush()
    audit.log(db, actor, "F10_TRAYECTORIA_ACTUALIZADA", "f10_semestre", f.id, None, estudiante_id=f.estudiante_id)
    return adv


# ============================================================================ aprobacion y plan siguiente
def _calendario(db: Session, est: Estudiante, semestre: str) -> CalendarioAcademico | None:
    for pid in (est.programa_id, None):
        c = db.scalar(select(CalendarioAcademico).where(
            CalendarioAcademico.semestre_academico == semestre,
            CalendarioAcademico.programa_id.is_(None) if pid is None else CalendarioAcademico.programa_id == pid))
        if c:
            return c
    return None


def crear_plan_siguiente(db: Session, f: F10Semestre, est: Estudiante, actor: Usuario) -> dict[str, Any]:
    """Plan del siguiente semestre en BORRADOR con los ajustes/estrategias que se mantienen o modifican."""
    if f.plan_id is None:
        return {"creado": False, "plan_id": None, "motivo": "El F10 no tiene plan de origen."}
    existente = _plan_de_semestre(db, est.id, f.semestre_destino)
    if existente is not None:
        f.plan_siguiente_id = existente.id
        return {"creado": False, "plan_id": existente.id,
                "motivo": f"Ya existe un plan activo para {f.semestre_destino}; no se duplicó."}
    origen = db.get(PlanMaarTea, f.plan_id)
    cal = _calendario(db, est, f.semestre_destino)
    inicio = cal.fecha_inicio if cal else date.today()
    plan = PlanMaarTea(
        estudiante_id=est.id, fecha_elaboracion=date.today(), semestre_academico=f.semestre_destino,
        profesionales_responsables_ids=origen.profesionales_responsables_ids, participacion_estudiante=True,
        participacion_familia=origen.participacion_familia, vigencia_inicio=inicio,
        vigencia_fin=cal.fecha_fin if cal else None, estado=EstadoPlanEnum.BORRADOR, version=1,
        resumen_ejecutivo=f"Borrador generado desde el F10 del semestre {f.semestre_origen}. Revise cada ajuste con el estudiante.",
        elaborado_por_id=f.aprobado_bienestar_por_id or actor.id,
    )
    db.add(plan)
    db.flush()
    copiados = estrategias = retirados = 0
    for it in (f.actualizacion_plan or {}).get("items", []):
        if it.get("informativo"):
            continue
        if it["tipo_decision"] == "RETIRAR":
            retirados += 1
            continue
        mod = it["tipo_decision"] == "MODIFICAR"
        if it["elemento"] == "AJUSTE":
            a = db.get(AjusteRazonable, it["elemento_id"])
            if a is None or a.plan_id != origen.id:
                continue
            nuevo = AjusteRazonable(
                plan_id=plan.id, barrera_asociada_id=a.barrera_asociada_id, nombre_ajuste=a.nombre_ajuste,
                descripcion_ajuste=it["descripcion_cambio"] if mod else a.descripcion_ajuste,
                justificacion=(a.justificacion + (f" | Modificado en F10: {it['justificacion']}" if mod and it.get("justificacion") else "")),
                tipo_ajuste=a.tipo_ajuste, especificidad=a.especificidad, asignatura_si_aplica=a.asignatura_si_aplica,
                actividad_si_aplica=a.actividad_si_aplica, fecha_inicio=inicio,
                fecha_fin_prevista=None if a.permanencia_indefinida else plan.vigencia_fin,
                permanencia_indefinida=a.permanencia_indefinida, estado=EstadoAjuste.PROPUESTO,
                asignatura_id=a.asignatura_id, responsable_id=a.responsable_id, fortaleza_apoyo_id=a.fortaleza_apoyo_id,
                frecuencia=a.frecuencia, indicador_efectividad=a.indicador_efectividad,
            )
            db.add(nuevo)
            db.flush()
            for modelo in _RESPUESTAS:
                for r in db.scalars(select(modelo).where(modelo.ajuste_id == a.id)):
                    cols = {c.name: getattr(r, c.name) for c in modelo.__table__.columns
                            if c.name not in ("id", "created_at", "updated_at", "deleted_at", "deleted_reason",
                                              "deleted_by_id", "ajuste_id")}
                    db.add(modelo(ajuste_id=nuevo.id, **cols))
            copiados += 1
        elif it["elemento"] == "ESTRATEGIA":
            e = db.get(EstrategiaDua, it["elemento_id"])
            if e is None or e.plan_id != origen.id:
                continue
            db.add(EstrategiaDua(
                plan_id=plan.id, nombre_estrategia=e.nombre_estrategia,
                descripcion=it["descripcion_cambio"] if mod else e.descripcion, dimension_dua=e.dimension_dua,
                responsable_implementacion_id=e.responsable_implementacion_id, alcance=e.alcance,
                estado_implementacion=EstadoImplementacionDua.PLANEADA, estrategia_catalogo_id=e.estrategia_catalogo_id,
                asignatura_id=e.asignatura_id, escenario=e.escenario))
            estrategias += 1
    db.flush()
    f.plan_siguiente_id = plan.id
    return {"creado": True, "plan_id": plan.id, "ajustes_copiados": copiados, "estrategias_copiadas": estrategias,
            "retirados": retirados}


def aprobar(db: Session, f: F10Semestre, est: Estudiante, user: Usuario, comentario: str | None = None) -> dict[str, Any]:
    if f.estado == EstadoF10.APROBADO:
        raise Conflict("Este F10 ya está aprobado.", "F10_YA_APROBADO")
    ahora = utcnow()
    rol = str(user.rol)
    if rol == Rol.BIENESTAR:
        if f.aprobado_bienestar_at is not None:
            raise Conflict("Usted ya aprobó este F10; falta la aprobación del estudiante.", "F10_YA_APROBADO_POR_USTED")
        f.aprobado_bienestar_por_id, f.aprobado_bienestar_at = user.id, ahora
    elif rol == Rol.ESTUDIANTE:
        if f.aprobado_estudiante_at is not None:
            raise Conflict("Usted ya aprobó este F10; falta la aprobación de Bienestar.", "F10_YA_APROBADO_POR_USTED")
        f.aprobado_estudiante_por_id, f.aprobado_estudiante_at = user.id, ahora
        f.comentario_estudiante = comentario
    else:
        raise Forbidden("Solo Bienestar y el estudiante aprueban el F10.", "ROL_NO_PERMITIDO")
    resultado: dict[str, Any] = {"plan_siguiente": None}
    if f.aprobado_bienestar_at and f.aprobado_estudiante_at:
        f.estado, f.aprobado_at = EstadoF10.APROBADO, ahora
        resultado["plan_siguiente"] = crear_plan_siguiente(db, f, est, user)
        _hito_cambio_semestre(db, f, est, user)
    else:
        f.estado = EstadoF10.PENDIENTE_APROBACION
        if rol == Rol.BIENESTAR:
            notify(db, Evento.F10_PENDIENTE_APROBACION, [est.usuario_id],
                   {"enlace": "/estudiante/f10"}, dedupe_key=f"f10:{f.id}:aprob:{ahora.isoformat()}")
    db.flush()
    audit.log(db, user, "F10_APROBADO_POR_" + rol, "f10_semestre", f.id,
              {"estado": str(f.estado), "plan_siguiente": resultado["plan_siguiente"]}, estudiante_id=est.id)
    return resultado


def _hito_cambio_semestre(db: Session, f: F10Semestre, est: Estudiante, user: Usuario) -> None:
    ya = db.scalar(select(HitoTrayectoria).where(
        HitoTrayectoria.estudiante_id == est.id, HitoTrayectoria.tipo_hito == TipoHito.CAMBIO_SEMESTRE,
        HitoTrayectoria.trayectoria_id == f.trayectoria_id))
    if ya is None:
        db.add(HitoTrayectoria(
            estudiante_id=est.id, trayectoria_id=f.trayectoria_id, tipo_hito=TipoHito.CAMBIO_SEMESTRE,
            fecha_hito=date.today(), descripcion=f"Cierre del semestre {f.semestre_origen} (F10 aprobado); "
            f"inicia {f.semestre_destino}.", registrado_por_id=user.id))


# ============================================================================ notas de continuidad (RF-35)
def _es_bienestar_del_estudiante(est: Estudiante, user: Usuario) -> bool:
    return str(user.rol) == Rol.BIENESTAR and est.bienestar_asignado_id == user.id


def nota_visible(db: Session, n: NotaContinuidad, user: Usuario, est: Estudiante | None = None) -> bool:
    """RF-35: solo lo APROBADO llega a nuevos actores. Estudiante: todo lo suyo. Bienestar: lo que elaboro / sus estudiantes
    asignados (bienestar_asignado_id) y lo aprobado; un profesional nuevo ve solo lo aprobado. Coordinador: solo aprobado (TODOS/COORDINADOR). Docente/Familiar/Admin: nunca (matriz §12.1)."""
    est = est or db.get(Estudiante, n.estudiante_id)
    rol = str(user.rol)
    aprobada = str(n.estado) == N.APROBADA
    if rol == Rol.ESTUDIANTE:
        return est.usuario_id == user.id
    if rol == Rol.BIENESTAR:
        return n.elaborada_por_id == user.id or _es_bienestar_del_estudiante(est, user) \
            or (aprobada and str(n.destinatario) in ("TODOS", "BIENESTAR"))
    if rol == Rol.COORDINADOR:
        return aprobada and str(n.destinatario) in ("TODOS", "COORDINADOR")
    return False


def notas_visibles(db: Session, f: F10Semestre, user: Usuario) -> list[NotaContinuidad]:
    est = db.get(Estudiante, f.estudiante_id)
    todas = db.scalars(select(NotaContinuidad).where(
        NotaContinuidad.estudiante_id == f.estudiante_id, NotaContinuidad.semestre_origen == f.semestre_origen)
        .order_by(NotaContinuidad.id))
    return [n for n in todas if nota_visible(db, n, user, est)]


def notas_aprobadas_destino(db: Session, estudiante_id: int, semestre_destino: str, user: Usuario) -> list[NotaContinuidad]:
    """Para nuevos actores: notas APROBADAS dirigidas al semestre que inicia, segun el alcance del rol."""
    est = db.get(Estudiante, estudiante_id)
    todas = db.scalars(select(NotaContinuidad).where(
        NotaContinuidad.estudiante_id == estudiante_id, NotaContinuidad.semestre_destino == semestre_destino,
        NotaContinuidad.estado == N.APROBADA).order_by(NotaContinuidad.id))
    return [n for n in todas if nota_visible(db, n, user, est)]


def serializar_nota(db: Session, n: NotaContinuidad, user: Usuario, advertencia: str | None = None) -> dict[str, Any]:
    autor = db.get(Usuario, n.elaborada_por_id)
    return {
        "id": n.id, "estudiante_id": n.estudiante_id, "plan_id": n.plan_id, "semestre_origen": n.semestre_origen,
        "semestre_destino": n.semestre_destino, "destinatario": str(n.destinatario), "estado": str(n.estado),
        "contenido": n.contenido, "elaborada_por_id": n.elaborada_por_id,
        "elaborada_por_rol": str(autor.rol) if autor else None, "aprobada_por_estudiante": n.aprobada_por_estudiante,
        "aprobada_at": n.aprobada_at, "motivo_rechazo": n.motivo_rechazo, "created_at": n.created_at,
        "updated_at": n.updated_at, "advertencia": advertencia,
    }


def get_nota_or_404(db: Session, f: F10Semestre, nota_id: int) -> NotaContinuidad:
    n = db.get(NotaContinuidad, nota_id)
    if n is None or n.estudiante_id != f.estudiante_id or n.semestre_origen != f.semestre_origen:
        raise NotFound("No encontramos esa nota de continuidad.", "NOTA_NO_ENCONTRADA")
    return n


def crear_nota(db: Session, f: F10Semestre, user: Usuario, contenido: str, destinatario: str) -> NotaContinuidad:
    n = NotaContinuidad(
        estudiante_id=f.estudiante_id, plan_id=f.plan_id, semestre_origen=f.semestre_origen,
        semestre_destino=f.semestre_destino, destinatario=destinatario, contenido=contenido, estado=N.BORRADOR,
        elaborada_por_id=user.id, aprobada_por_estudiante=False)
    db.add(n)
    db.flush()
    audit.log(db, user, "NOTA_CONTINUIDAD_CREADA", "nota_continuidad", n.id, {"destinatario": destinatario},
              estudiante_id=f.estudiante_id)
    return n


def editar_nota(db: Session, n: NotaContinuidad, user: Usuario, contenido: str | None, destinatario: str | None) -> str | None:
    """Editar invalida cualquier aprobacion/rechazo previo: la nota vuelve a BORRADOR (no disponible)."""
    adv = None
    if str(n.estado) in (N.APROBADA, N.PENDIENTE_APROBACION_ESTUDIANTE, N.RECHAZADA):
        adv = "La nota volvió a BORRADOR: el estudiante debe aprobarla de nuevo para que otros la puedan ver."
    if contenido is not None:
        n.contenido = contenido
    if destinatario is not None:
        n.destinatario = destinatario
    n.estado, n.aprobada_por_estudiante, n.aprobada_at, n.motivo_rechazo = N.BORRADOR, False, None, None
    db.flush()
    audit.log(db, user, "NOTA_CONTINUIDAD_EDITADA", "nota_continuidad", n.id, None, estudiante_id=n.estudiante_id)
    return adv


def enviar_nota(db: Session, n: NotaContinuidad, user: Usuario, est: Estudiante) -> None:
    if str(n.estado) not in (N.BORRADOR, N.RECHAZADA):
        raise Conflict("Solo se pueden enviar a aprobación notas en borrador o rechazadas.", "NOTA_ESTADO_INVALIDO")
    n.estado, n.motivo_rechazo = N.PENDIENTE_APROBACION_ESTUDIANTE, None
    notify(db, Evento.NOTA_CONTINUIDAD_PENDIENTE, [est.usuario_id], {"enlace": "/estudiante/f10"},
           dedupe_key=f"nota:{n.id}:{utcnow().isoformat()}")
    db.flush()
    audit.log(db, user, "NOTA_CONTINUIDAD_ENVIADA", "nota_continuidad", n.id, None, estudiante_id=n.estudiante_id)


def aprobar_nota(db: Session, n: NotaContinuidad, user: Usuario) -> None:
    autor_es_estudiante = n.elaborada_por_id == user.id
    if str(n.estado) != N.PENDIENTE_APROBACION_ESTUDIANTE and not (autor_es_estudiante and str(n.estado) == N.BORRADOR):
        raise Conflict("Esta nota no está esperando su aprobación.", "NOTA_ESTADO_INVALIDO")
    n.estado, n.aprobada_por_estudiante, n.aprobada_at, n.motivo_rechazo = N.APROBADA, True, utcnow(), None
    db.flush()
    audit.log(db, user, "NOTA_CONTINUIDAD_APROBADA", "nota_continuidad", n.id, None, estudiante_id=n.estudiante_id)


def rechazar_nota(db: Session, n: NotaContinuidad, user: Usuario, motivo: str) -> None:
    if str(n.estado) != N.PENDIENTE_APROBACION_ESTUDIANTE:
        raise Conflict("Esta nota no está esperando su aprobación.", "NOTA_ESTADO_INVALIDO")
    n.estado, n.aprobada_por_estudiante, n.aprobada_at, n.motivo_rechazo = N.RECHAZADA, False, None, motivo
    db.flush()
    audit.log(db, user, "NOTA_CONTINUIDAD_RECHAZADA", "nota_continuidad", n.id, None, estudiante_id=n.estudiante_id)


# ============================================================================ integraciones
def contexto_para_f3(db: Session, estudiante_id: int, semestre: str) -> dict[str, Any] | None:
    """Contexto inicial del F3 del `semestre` a partir del F10 APROBADO que lo tiene como destino (None si no hay).

    Solo datos no clinicos: decisiones sobre apoyos, resumen de trayectoria y escenarios/necesidades anticipadas.
    Nunca incluye el texto de las notas de continuidad (solo cuantas fueron aprobadas)."""
    f = db.scalar(select(F10Semestre).where(
        F10Semestre.estudiante_id == estudiante_id, F10Semestre.semestre_destino == semestre,
        F10Semestre.estado == EstadoF10.APROBADO).order_by(F10Semestre.id.desc()))
    if f is None:
        return None
    est = db.get(Estudiante, estudiante_id)
    items = [i for i in (f.actualizacion_plan or {}).get("items", []) if not i.get("informativo")]
    resumen = {k: [i["nombre"] for i in items if i["tipo_decision"] == k] for k in ("MANTENER", "MODIFICAR", "RETIRAR")}
    escenarios: list[str] = []
    for n in f.necesidades_anticipadas or []:
        if n["tipo"] == "PRACTICAS":
            escenarios += ["PRACTICA_CLINICA", "PRACTICA_SALUD_PUBLICA"]
        elif n["tipo"] == "PASANTIAS":
            escenarios.append("PASANTIAS")
    for n in ((f.proyeccion or {}).get("siguiente_semestre") or {}).get("necesidades", []):
        escenarios += n.get("escenarios_sugeridos", [])
    for a in ((f.proyeccion or {}).get("siguiente_semestre") or {}).get("asignaturas", []):
        if a.get("escenario_predominante"):
            escenarios.append(a["escenario_predominante"])
    escenarios = ["AULA", "CAMPUS"] + [e for e in dict.fromkeys(escenarios) if e not in ("AULA", "CAMPUS")]
    notas_ok = db.scalars(select(NotaContinuidad.id).where(
        NotaContinuidad.estudiante_id == estudiante_id, NotaContinuidad.semestre_destino == semestre,
        NotaContinuidad.estado == N.APROBADA)).all()
    return {
        "f10_id": f.id, "semestre_origen": f.semestre_origen, "semestre_destino": f.semestre_destino,
        "plan_siguiente_id": f.plan_siguiente_id, "decisiones_plan": resumen,
        "nuevos_propuestos": (f.actualizacion_plan or {}).get("nuevos_propuestos", []),
        "trayectoria": svc_tray.resumen_trayectoria(db, est) if est else None,
        "necesidades_anticipadas": f.necesidades_anticipadas or [],
        "escenarios_sugeridos": escenarios,
        "proyeccion_siguiente_semestre": (f.proyeccion or {}).get("siguiente_semestre"),
        "notas_continuidad_aprobadas": len(notas_ok),
    }


@dataclass(frozen=True)
class EstudiantePracticas:
    estudiante_id: int
    usuario_id: int
    nombre: str
    programa_id: int
    semestre_actual: int
    semestre_practicas: int
    bienestar_asignado_id: int | None

    @property
    def semestres_para_practicas(self) -> int:
        return self.semestre_practicas - self.semestre_actual  # 0 = ya esta en el semestre de practicas


def estudiantes_en_practicas(db: Session, semestre: str | None = None, anticipacion: int = 0) -> list[EstudiantePracticas]:
    """Estudiantes ACTIVOS cuyo nivel (`semestre_actual`) esta en el semestre de practicas del programa
    (`anticipacion`=1 incluye a quienes lo inician el semestre siguiente). `semestre` ("2026-II") no filtra: se usa
    para la llave de idempotencia de la alerta."""
    filas = db.execute(
        select(Estudiante, ProgramaAcademico, Usuario)
        .join(ProgramaAcademico, ProgramaAcademico.id == Estudiante.programa_id)
        .join(Usuario, Usuario.id == Estudiante.usuario_id)
        .where(ProgramaAcademico.semestre_practicas.is_not(None), Estudiante.semestre_actual.is_not(None),
               Estudiante.estado_academico == "ACTIVO", Usuario.estado == EstadoUsuario.ACTIVO)
    ).all()
    out = []
    for est, prog, usr in filas:
        if prog.semestre_practicas - anticipacion <= est.semestre_actual <= prog.semestre_practicas:
            out.append(EstudiantePracticas(est.id, usr.id, usr.nombre_completo, prog.id, est.semestre_actual,
                                           prog.semestre_practicas, est.bienestar_asignado_id))
    return out


def notificar_semestre_practicas(db: Session, semestre: str, anticipacion: int = 0) -> int:
    """Alerta «Estudiante entra a semestre de prácticas» a Bienestar (idempotente). Devuelve estudiantes avisados."""
    n = 0
    todos_bienestar = get_notification_user_ids(db, "BIENESTAR")
    for e in estudiantes_en_practicas(db, semestre, anticipacion):
        destinos = [e.bienestar_asignado_id] if e.bienestar_asignado_id else todos_bienestar
        if not destinos:
            continue
        notify(db, Evento.SEMESTRE_PRACTICAS, destinos,
               {"estudiante_nombre": e.nombre, "enlace": f"/bienestar/estudiantes/{e.estudiante_id}"},
               dedupe_key=f"practicas:{e.estudiante_id}:{e.semestre_practicas}:{semestre}")
        n += 1
    return n
