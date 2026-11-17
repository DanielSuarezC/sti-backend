"""Serialización del Plan MAAR-TEA por rol (slice C1).

* Vista COMPLETA: Bienestar, Coordinador, Estudiante (el suyo), Familiar autorizado (solo lectura) y Admin.
* Vista DOCENTE: solo SUS ajustes y estrategias, sin datos clínicos (sin descripción de la barrera, fortaleza,
  justificación, comentarios del estudiante, negociaciones, bitácora ni resumen del plan).
El semáforo por ajuste es solo lectura: el último `REGISTRO_SEGUIMIENTO_AJUSTE` (lo escribe el slice C2).
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import docente_ajuste_ids
from app.models.academico import Asignatura, ProgramaAcademico
from app.models.caracterizacion import Fortaleza
from app.models.enums import Rol
from app.models.mapa import BarreraIdentificada
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea
from app.models.seguimiento import RegistroSeguimientoAjuste
from app.models.usuarios import Usuario
from app.services import negotiation
from app.services import plan_categorias as cats
from app.services import plan_common as common
from app.services import plan_signatures as sig
from app.services import plan_workflow as wf

TEXTO_SEMAFORO = {
    "VERDE": "Verde: el ajuste funciona",
    "AMARILLO": "Amarillo: funciona en parte, hay que concertar cambios",
    "ROJO": "Rojo: no funciona, se debe rediseñar",
}


def semaforos(db: Session, ajuste_ids: list[int]) -> dict[int, dict]:
    """Último registro de seguimiento por ajuste (solo lectura)."""
    if not ajuste_ids:
        return {}
    db.flush()
    out: dict[int, dict] = {}
    rows = db.scalars(select(RegistroSeguimientoAjuste).where(RegistroSeguimientoAjuste.ajuste_id.in_(ajuste_ids))
                      .order_by(RegistroSeguimientoAjuste.corte, RegistroSeguimientoAjuste.id))
    for r in rows:  # el último gana
        out[r.ajuste_id] = {"valor": str(r.semaforo), "corte": str(r.corte), "texto": TEXTO_SEMAFORO[str(r.semaforo)],
                            "fecha": (r.semaforo_cambiado_at or r.created_at).isoformat()}
    return out


def _semaforo_de(a: AjusteRazonable, sem: dict[int, dict]) -> dict | None:
    if a.id in sem:
        return sem[a.id]
    if a.semaforo_actual:
        v = str(a.semaforo_actual)
        return {"valor": v, "corte": None, "texto": TEXTO_SEMAFORO[v], "fecha": None}
    return None


def _barrera(db: Session, barrera_id: int | None, clinica: bool) -> dict | None:
    if barrera_id is None:
        return None
    b = db.get(BarreraIdentificada, barrera_id)
    if b is None:
        return None
    out = {"id": b.id, "tipo_barrera": str(b.tipo_barrera), "escenario": str(b.escenario) if b.escenario else None}
    if clinica:
        out["descripcion_barrera"] = b.descripcion_barrera
        out["severidad"] = str(b.severidad)
    return out


def _fortaleza(db: Session, fid: int | None) -> dict | None:
    if fid is None:
        return None
    f = db.get(Fortaleza, fid)
    return {"id": f.id, "nombre_fortaleza": f.nombre_fortaleza} if f else None


def serializar_ajuste(db: Session, a: AjusteRazonable, *, docente: bool, sem: dict[int, dict],
                      tareas: dict[int, dict]) -> dict:
    asig = db.get(Asignatura, a.asignatura_id) if a.asignatura_id else None
    out = {
        "id": a.id, "plan_id": a.plan_id, "nombre_ajuste": a.nombre_ajuste, "descripcion_ajuste": a.descripcion_ajuste,
        "tipo_ajuste": str(a.tipo_ajuste), "categoria": cats.categoria(a.tipo_ajuste).etiqueta,
        "detalle": cats.leer_detalle(db, a), "barrera": _barrera(db, a.barrera_asociada_id, not docente),
        "responsable": common.ref_usuario(db, a.responsable_id),
        "asignatura": {"id": asig.id, "codigo": asig.codigo, "nombre": asig.nombre} if asig else None,
        "asignatura_si_aplica": a.asignatura_si_aplica, "actividad_si_aplica": a.actividad_si_aplica,
        "especificidad": str(a.especificidad), "recurso": a.recurso, "frecuencia": a.frecuencia,
        "indicador_efectividad": a.indicador_efectividad, "fecha_inicio": a.fecha_inicio.isoformat(),
        "fecha_fin_prevista": a.fecha_fin_prevista.isoformat() if a.fecha_fin_prevista else None,
        "permanencia_indefinida": a.permanencia_indefinida, "estado": str(a.estado),
        "aceptado_por_estudiante": a.aceptado_por_estudiante,
        "aceptacion_docente": {"aceptado": a.aceptado_por_responsable, "comentario": a.comentario_responsable,
                               "fecha": a.aceptado_por_responsable_at.isoformat() if a.aceptado_por_responsable_at else None},
        "semaforo": _semaforo_de(a, sem),
    }
    if not docente:
        out.update({
            "justificacion": a.justificacion, "fortaleza": _fortaleza(db, a.fortaleza_apoyo_id), "origen": a.origen,
            "propuesto_por": ({"id": a.propuesto_por_id, "rol": a.propuesto_por_rol,
                               "nombre_completo": common.nombre_usuario(db, a.propuesto_por_id)}
                              if a.propuesto_por_rol else None),
            "modificado_por": common.ref_usuario(db, a.modificado_por_id),
            "modificado_at": a.modificado_at.isoformat() if a.modificado_at else None,
            "respuesta_estudiante": {
                "respuesta": a.respuesta_estudiante, "comentario": a.comentario_estudiante,
                "modificacion_propuesta": a.modificacion_propuesta,
                "fecha": a.aceptado_por_estudiante_at.isoformat() if a.aceptado_por_estudiante_at else None},
            "negociacion": tareas.get(a.id),
        })
    return out


def serializar_estrategia(db: Session, e: EstrategiaDua, *, docente: bool) -> dict:
    asig = db.get(Asignatura, e.asignatura_id) if e.asignatura_id else None
    out = {
        "id": e.id, "plan_id": e.plan_id, "nombre_estrategia": e.nombre_estrategia, "descripcion": e.descripcion,
        "dimension_dua": str(e.dimension_dua), "alcance": e.alcance, "escenario": str(e.escenario) if e.escenario else None,
        "responsable": common.ref_usuario(db, e.responsable_implementacion_id),
        "asignatura": {"id": asig.id, "codigo": asig.codigo, "nombre": asig.nombre} if asig else None,
        "fecha_inicio_implementacion": e.fecha_inicio_implementacion.isoformat() if e.fecha_inicio_implementacion else None,
        "estado_implementacion": str(e.estado_implementacion), "implementada": e.implementada,
        "estrategia_catalogo_id": e.estrategia_catalogo_id, "sugerencia_id": e.sugerencia_id,
        "barrera": _barrera(db, e.barrera_id, not docente),
    }
    if not docente:
        out.update({
            "fortaleza": _fortaleza(db, e.fortaleza_id), "origen": e.origen,
            "propuesta_por": ({"id": e.propuesta_por_id, "rol": e.propuesta_por_rol,
                               "nombre_completo": common.nombre_usuario(db, e.propuesta_por_id)} if e.propuesta_por_rol else None),
            "modificado_por": common.ref_usuario(db, e.modificado_por_id),
        })
    return out


def _ids_visibles_docente(db: Session, plan: PlanMaarTea, user: Usuario) -> tuple[set[int], set[int]]:
    aj = docente_ajuste_ids(db, user, plan.id)
    from app.core.permissions import docente_asignatura_ids_stmt

    asig = set(db.scalars(docente_asignatura_ids_stmt(user)))
    es = {e.id for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id))
          if e.asignatura_id in asig or e.responsable_implementacion_id == user.id}
    return aj, es


def serializar_plan(db: Session, plan: PlanMaarTea, user: Usuario) -> dict:
    db.flush()
    docente = str(user.rol) == Rol.DOCENTE
    est = common.estudiante_de(db, plan)
    prog = db.get(ProgramaAcademico, est.programa_id) if est.programa_id else None
    ajustes = list(db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id)))
    estrategias = list(db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id).order_by(EstrategiaDua.id)))
    if docente:
        aj_ids, es_ids = _ids_visibles_docente(db, plan, user)
        ajustes = [a for a in ajustes if a.id in aj_ids]
        estrategias = [e for e in estrategias if e.id in es_ids]
    sem = semaforos(db, [a.id for a in ajustes])
    tareas_por_ajuste: dict[int, dict] = {}
    if not docente:
        for t in negotiation.tareas_del_plan(db, plan.id):  # la última por ajuste gana
            if t.ajuste_id:
                tareas_por_ajuste[t.ajuste_id] = {"id": t.id, "estado": str(t.estado), "ciclo": t.ciclo,
                                                  "max_ciclos": negotiation.max_ciclos(db),
                                                  "siguiente_accion": negotiation.siguiente_accion(t)}
    aj_out = [serializar_ajuste(db, a, docente=docente, sem=sem, tareas=tareas_por_ajuste) for a in ajustes]
    es_out = [serializar_estrategia(db, e, docente=docente) for e in estrategias]
    resumen = {
        "total_ajustes": len(aj_out), "total_estrategias_dua": len(es_out),
        "por_categoria": dict(Counter(a["tipo_ajuste"] for a in aj_out)),
        "por_semaforo": dict(Counter(a["semaforo"]["valor"] for a in aj_out if a["semaforo"])),
        "aceptados_por_estudiante": sum(1 for a in ajustes if a.aceptado_por_estudiante is True),
        "pendientes_estudiante": sum(1 for a in ajustes if a.aceptado_por_estudiante is None),
        "objetados": sum(1 for a in ajustes if a.aceptado_por_estudiante is False),
        "pendientes_docente": sum(1 for a in ajustes if a.responsable_id and a.aceptado_por_responsable is None),
    }
    out = {
        "id": plan.id, "vista": "DOCENTE" if docente else "COMPLETA",
        "estudiante": {"id": est.id, "nombre_completo": common.nombre_usuario(db, est.usuario_id),
                       "codigo_estudiante": est.codigo_estudiante, "programa_id": est.programa_id,
                       "programa": prog.nombre_programa if prog else None},
        "semestre_academico": plan.semestre_academico, "estado": str(plan.estado), "version": plan.version,
        "fecha_elaboracion": plan.fecha_elaboracion.isoformat(), "vigencia_inicio": plan.vigencia_inicio.isoformat(),
        "vigencia_fin": plan.vigencia_fin.isoformat() if plan.vigencia_fin else None,
        "fecha_aprobacion": plan.fecha_aprobacion.isoformat() if plan.fecha_aprobacion else None,
        "ciclos_negociacion": plan.ciclos_negociacion, "semaforo_actual": str(plan.semaforo_actual) if plan.semaforo_actual else None,
        "elaborado_por": common.ref_usuario(db, plan.elaborado_por_id),
        "ajustes": aj_out, "estrategias_dua": es_out, "resumen": resumen,
        "acciones_disponibles": wf.acciones_disponibles(db, plan, user),
        "matriz_generada": False,
    }
    from app.services import plan_builder

    out["matriz_generada"] = plan_builder.tiene_matriz(db, plan.id)
    if docente:
        return out
    firmas = sig.firmas_de(db, plan.id, plan.version)
    st = sig.estado_firmas(db, plan)
    out.update({
        "resumen_ejecutivo": plan.resumen_ejecutivo, "justificacion_apoyos": plan.justificacion_apoyos,
        "participacion_estudiante": plan.participacion_estudiante, "participacion_familia": plan.participacion_familia,
        "validado_por": common.ref_usuario(db, plan.validado_por_id),
        "fecha_validacion": plan.fecha_validacion.isoformat() if plan.fecha_validacion else None,
        "comentarios_validacion": plan.comentarios_validacion,
        "enviado_a_estudiante_at": plan.enviado_a_estudiante_at.isoformat() if plan.enviado_a_estudiante_at else None,
        "firmas": [serializar_firma(db, f) for f in firmas], "firmas_estado": st,
        "hash_contenido": sig.hash_contenido(sig.contenido_canonico(db, plan)),
        "puede_enviar_a_validacion": not wf.razones_no_listo_para_validacion(db, plan) if plan.estado == "EN_CONCERTACION" else False,
        "razones_no_listo": wf.razones_no_listo_para_validacion(db, plan) if plan.estado == "EN_CONCERTACION" else [],
        "negociaciones_abiertas": [negotiation.serializar(db, t, plan) for t in wf.tareas_abiertas(db, plan.id)],
        "participacion": plan.participacion_log or [],
    })
    if str(user.rol) == Rol.FAMILIAR:
        out["participacion"] = []
        out["negociaciones_abiertas"] = []
    return out


def serializar_firma(db: Session, f) -> dict:
    return {
        "id": f.id, "version": f.version, "rol_firmante": str(f.rol_firmante),
        "firmante": common.ref_usuario(db, f.firmante_id), "firmado_at": f.firmado_at.isoformat(),
        "estado": str(f.estado), "hash_documento": f.hash_documento, "hash_corto": sig.hash_corto(f.hash_documento),
        "firma_hash": f.firma_hash, "ip": f.ip,
    }


def item_listado(db: Session, plan: PlanMaarTea) -> dict:
    est = common.estudiante_de(db, plan)
    n_aj = len(list(db.scalars(select(AjusteRazonable.id).where(AjusteRazonable.plan_id == plan.id))))
    return {
        "id": plan.id, "estudiante_id": est.id, "estudiante_nombre": common.nombre_usuario(db, est.usuario_id),
        "programa_id": est.programa_id, "semestre_academico": plan.semestre_academico, "estado": str(plan.estado),
        "version": plan.version, "total_ajustes": n_aj, "semaforo_actual": str(plan.semaforo_actual) if plan.semaforo_actual else None,
        "fecha_elaboracion": plan.fecha_elaboracion.isoformat(),
        "fecha_aprobacion": plan.fecha_aprobacion.isoformat() if plan.fecha_aprobacion else None,
        "updated_at": plan.updated_at.isoformat(),
    }
