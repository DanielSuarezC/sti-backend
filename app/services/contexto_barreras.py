"""F3 contexto por escenarios (RF-17), F4 barreras (RF-18/19) y F5 facilitadores (RF-20), vínculo barrera-facilitador.

Lenguaje del sistema: la barrera es del entorno, no de la persona.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.contexto import ContextoDocente, ContextoEvaluacion, ContextoUniversitario
from app.models.enums import Escenario, EstadoBarrera, EstadoNotaContinuidad, TipoBarrera, TipoHito
from app.models.evaluacion import NotaContinuidad
from app.models.mapa import BarreraIdentificada, Facilitador
from app.models.slice_b import BarreraFacilitador
from app.models.trayectoria import HitoTrayectoria
from app.models.usuarios import Estudiante, Usuario
from app.schemas.contexto_barreras import (
    BARRERA_DETALLE_IN,
    BARRERA_DETALLE_PATCH,
    BARRERA_MODELOS,
    ESCENARIO_MODELOS,
    ESCENARIO_NOMBRES,
    FACILITADOR_DETALLE_IN,
    FACILITADOR_DETALLE_PATCH,
    FACILITADOR_MODELOS,
)
from app.services.b_common import semestre_anterior, semestre_de, semestre_valido
from app.services.caracterizacion import has_confirmed_f1

_EXCL = {"id", "created_at", "updated_at", "deleted_at", "deleted_reason", "deleted_by_id"}


def _dump(obj: Any, extra: set[str] | None = None) -> dict[str, Any]:
    ex = _EXCL | (extra or set())
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns if c.key not in ex}


def _validate(schema, data: dict, ctx: str):
    try:
        return schema.model_validate(data or {})
    except ValidationError as e:
        det = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
        raise Unprocessable(f"Revise los detalles de {ctx}: {det}.", "DETALLE_INVALIDO",
                            extra={"errores": [{"campo": ".".join(map(str, x["loc"])), "mensaje": x["msg"]} for x in e.errors()]}) from None


# ============================================================================ F3
def get_context(db: Session, est_id: int, semestre: str) -> ContextoUniversitario | None:
    return db.scalar(select(ContextoUniversitario).where(ContextoUniversitario.estudiante_id == est_id,
                                                         ContextoUniversitario.semestre_academico == semestre))


def check_semestre(semestre: str) -> str:
    if not semestre_valido(semestre):
        raise Unprocessable("El semestre debe tener el formato AAAA-I o AAAA-II (por ejemplo 2026-II).", "SEMESTRE_INVALIDO")
    return semestre


def _scenario_row(db: Session, ctx_id: int, esc: Escenario):
    m = ESCENARIO_MODELOS[esc]
    return db.scalar(select(m).where(m.contexto_universitario_id == ctx_id))


def create_context(db: Session, est: Estudiante, actor: Usuario, semestre: str, *, precargar: bool = True,
                   strict: bool = True) -> tuple[ContextoUniversitario, dict[str, Any]]:
    check_semestre(semestre)
    existing = get_context(db, est.id, semestre)
    if existing is not None:
        if strict:
            raise Conflict("Ya existe el análisis de contexto (F3) de ese semestre.", "CONTEXTO_YA_EXISTE")
        return existing, {}
    if est.programa_id is None:
        raise Unprocessable("El estudiante no tiene programa asignado: asígnelo antes de registrar el contexto.", "ESTUDIANTE_SIN_PROGRAMA")
    ctx = ContextoUniversitario(estudiante_id=est.id, programa_academico_id=est.programa_id, semestre_academico=semestre,
                                fecha_analisis=date.today(), responsable_analisis_id=actor.id)
    db.add(ctx)
    db.flush()
    precarga: dict[str, Any] = {"origen_semestre": None, "escenarios_copiados": [], "hitos_sugeridos": [],
                                "nota_continuidad_aprobada": False}
    if precargar:
        prev_sem = semestre_anterior(semestre)
        prev = get_context(db, est.id, prev_sem)
        if prev is not None:
            precarga["origen_semestre"] = prev_sem
            ctx.factores_protectores = prev.factores_protectores
            for esc, m in ESCENARIO_MODELOS.items():
                old = _scenario_row(db, prev.id, esc)
                if old is not None:
                    db.add(m(contexto_universitario_id=ctx.id, **_dump(old, {"contexto_universitario_id"})))
                    precarga["escenarios_copiados"].append(str(esc))
        hitos = db.scalars(select(HitoTrayectoria).where(HitoTrayectoria.estudiante_id == est.id,
                                                         HitoTrayectoria.tipo_hito == TipoHito.INICIO_PRACTICAS)).all()
        if hitos:
            for esc in (Escenario.PRACTICA_CLINICA, Escenario.PRACTICA_SALUD_PUBLICA):
                if _scenario_row(db, ctx.id, esc) is None and str(esc) not in precarga["escenarios_copiados"]:
                    db.flush()
                    db.add(ESCENARIO_MODELOS[esc](contexto_universitario_id=ctx.id, aplica=True,
                                                  observaciones="Sugerido desde F10: el estudiante tiene práctica anticipada."))
                    precarga["hitos_sugeridos"].append(str(esc))
        precarga["nota_continuidad_aprobada"] = db.scalar(
            select(NotaContinuidad.id).where(NotaContinuidad.estudiante_id == est.id,
                                             NotaContinuidad.estado == EstadoNotaContinuidad.APROBADA,
                                             NotaContinuidad.semestre_destino == semestre).limit(1)) is not None
    db.flush()
    return ctx, precarga


def save_scenario(db: Session, ctx: ContextoUniversitario, esc: Escenario, body) -> Any:
    m = ESCENARIO_MODELOS[esc]
    row = _scenario_row(db, ctx.id, esc)
    data = body.model_dump(exclude_unset=True)
    if row is None:
        row = m(contexto_universitario_id=ctx.id, **data)
        db.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    ctx.fecha_analisis = date.today()
    db.flush()
    return row


def save_docentes(db: Session, ctx: ContextoUniversitario, actor: Usuario, body) -> list[ContextoDocente]:
    rows = {r.id: r for r in db.scalars(select(ContextoDocente).where(ContextoDocente.contexto_universitario_id == ctx.id))}
    for it in body.items:
        data = it.model_dump(exclude_unset=True)
        iid = data.pop("id", None)
        if iid is not None:
            r = rows.get(iid)
            if r is None:
                raise Unprocessable(f"No existe el docente {iid} en este contexto.", "ELEMENTO_NO_ENCONTRADO")
            for k, v in data.items():
                setattr(r, k, v)
        else:
            nombre = (data.get("nombre_docente") or "").strip().lower()
            r = next((x for x in rows.values() if nombre and (x.nombre_docente or "").strip().lower() == nombre), None)
            if r is None:
                r = ContextoDocente(contexto_universitario_id=ctx.id, **data)
                db.add(r)
                db.flush()
                rows[r.id] = r
            else:
                for k, v in data.items():
                    setattr(r, k, v)
    for q in body.quitar:
        if q in rows and not rows[q].is_deleted:
            rows[q].soft_delete(actor.id, "Quitado por el usuario desde el formulario")
    db.flush()
    return [r for r in rows.values() if not r.is_deleted]


def save_evaluacion(db: Session, ctx: ContextoUniversitario, body) -> ContextoEvaluacion:
    r = db.scalar(select(ContextoEvaluacion).where(ContextoEvaluacion.contexto_universitario_id == ctx.id))
    data = body.model_dump(exclude_unset=True)
    if r is None:
        r = ContextoEvaluacion(contexto_universitario_id=ctx.id, **data)
        db.add(r)
    else:
        for k, v in data.items():
            setattr(r, k, v)
    db.flush()
    return r


def context_progress(db: Session, ctx: ContextoUniversitario | None) -> dict[str, Any]:
    esc_out = []
    decididos = completos = 0
    for esc in Escenario:
        row = _scenario_row(db, ctx.id, esc) if ctx else None
        decidido = row is not None
        completo = bool(decidido and (not row.aplica or (row.descripcion_condiciones or "").strip()))
        decididos += decidido
        completos += completo
        esc_out.append({"escenario": str(esc), "nombre": ESCENARIO_NOMBRES[esc], "decidido": decidido,
                        "aplica": row.aplica if row else None, "completo": completo})
    resumen_ok = bool(ctx and (ctx.resumen_contextual or "").strip())
    return {
        "semestre_academico": ctx.semestre_academico if ctx else None, "existe": ctx is not None,
        "escenarios": esc_out, "escenarios_decididos": decididos, "escenarios_completos": completos,
        "resumen_completo": resumen_ok, "porcentaje": round(100 * completos / len(Escenario)),
        "completo": completos == len(Escenario) and resumen_ok,
        "faltantes": [e["nombre"] for e in esc_out if not e["completo"]],
    }


def context_view(db: Session, ctx: ContextoUniversitario, precarga: dict | None = None) -> dict[str, Any]:
    esc = {}
    for e in Escenario:
        r = _scenario_row(db, ctx.id, e)
        esc[str(e)] = _dump(r, {"contexto_universitario_id"}) if r else None
    docs = db.scalars(select(ContextoDocente).where(ContextoDocente.contexto_universitario_id == ctx.id).order_by(ContextoDocente.id)).all()
    ev = db.scalar(select(ContextoEvaluacion).where(ContextoEvaluacion.contexto_universitario_id == ctx.id))
    out = {
        "id": ctx.id, "estudiante_id": ctx.estudiante_id, "semestre_academico": ctx.semestre_academico,
        "fecha_analisis": ctx.fecha_analisis.isoformat(), "responsable_analisis_id": ctx.responsable_analisis_id,
        "resumen_contextual": ctx.resumen_contextual, "factores_protectores": ctx.factores_protectores,
        "factores_de_riesgo": ctx.factores_de_riesgo, "escenarios": esc,
        "docentes": [{"id": d.id, **_dump(d, {"contexto_universitario_id"})} for d in docs],
        "evaluacion": _dump(ev, {"contexto_universitario_id"}) if ev else None,
        "progreso": context_progress(db, ctx),
    }
    if precarga is not None:
        out["precarga"] = precarga
    return out


# ============================================================================ F4
def assert_f1_confirmed(db: Session, est_id: int) -> None:
    """Regla de servicio `ck_caracterizacion_completa` (ERD §6.2): no hay barreras sin caracterización confirmada."""
    if not has_confirmed_f1(db, est_id):
        raise Conflict(
            "Antes de registrar barreras, la caracterización (F1) del estudiante debe estar confirmada. "
            "Complete y confirme el F1 e intente de nuevo.", "CARACTERIZACION_INCOMPLETA",
        )


def _detalle_row(db: Session, model, fk: str, parent_id: int):
    return db.scalar(select(model).where(getattr(model, fk) == parent_id).order_by(model.id))


def _check_social(tipo: TipoBarrera, detalle: dict) -> None:
    if tipo == TipoBarrera.SOCIAL and not str(detalle.get("propuesta_respuesta_institucional") or "").strip():
        raise Unprocessable(
            "Toda barrera social necesita al menos una propuesta de respuesta INSTITUCIONAL (no solo individual). "
            "Escríbala en detalle.propuesta_respuesta_institucional.", "BARRERA_SOCIAL_SIN_RESPUESTA_INSTITUCIONAL",
        )


def create_barrier(db: Session, est: Estudiante, actor: Usuario, body) -> BarreraIdentificada:
    assert_f1_confirmed(db, est.id)
    tipo = body.tipo_barrera
    det = _validate(BARRERA_DETALLE_IN[tipo], body.detalle, f"la barrera {tipo}")
    detalle = det.model_dump(exclude_unset=True)
    _check_social(tipo, detalle)
    if body.semestre_academico:
        check_semestre(body.semestre_academico)
    b = BarreraIdentificada(
        estudiante_id=est.id, tipo_barrera=tipo, escenario=body.escenario, descripcion_barrera=body.descripcion_barrera.strip(),
        contexto_aparicion=body.contexto_aparicion, frecuencia=body.frecuencia, severidad=body.severidad,
        impacto_participacion=body.impacto_participacion, impacto_aprendizaje=body.impacto_aprendizaje,
        impacto_bienestar=body.impacto_bienestar, impacto_permanencia=body.impacto_permanencia,
        origen_percibido=body.origen_percibido, fecha_identificacion=body.fecha_identificacion or date.today(),
        semestre_academico=body.semestre_academico or semestre_de(), registrada_por_id=actor.id,
    )
    db.add(b)
    db.flush()
    if detalle:
        db.add(BARRERA_MODELOS[tipo](barrera_id=b.id, **detalle))
    db.flush()
    return b


def update_barrier(db: Session, b: BarreraIdentificada, body) -> BarreraIdentificada:
    data = body.model_dump(exclude_unset=True)
    detalle_in = data.pop("detalle", None)
    if "semestre_academico" in data and data["semestre_academico"]:
        check_semestre(data["semestre_academico"])
    for k, v in data.items():
        if v is None and k in ("descripcion_barrera", "frecuencia", "severidad", "fecha_identificacion"):
            continue
        setattr(b, k, v)
    model = BARRERA_MODELOS[b.tipo_barrera]
    row = _detalle_row(db, model, "barrera_id", b.id)
    if detalle_in is not None:
        patch = _validate(BARRERA_DETALLE_PATCH[b.tipo_barrera], detalle_in, f"la barrera {b.tipo_barrera}").model_dump(exclude_unset=True)
        if row is None:
            _validate(BARRERA_DETALLE_IN[b.tipo_barrera], patch, f"la barrera {b.tipo_barrera}")
            row = model(barrera_id=b.id, **patch)
            db.add(row)
        else:
            for k, v in patch.items():
                setattr(row, k, v)
        db.flush()
    if b.tipo_barrera == TipoBarrera.SOCIAL:
        _check_social(b.tipo_barrera, {"propuesta_respuesta_institucional": row.propuesta_respuesta_institucional if row else None})
    db.flush()
    return b


def mark_persistent(db: Session, b: BarreraIdentificada) -> BarreraIdentificada:
    if b.estado == EstadoBarrera.PERSISTENTE:
        return b
    b.estado = EstadoBarrera.PERSISTENTE
    db.flush()
    return b


def get_barrier(db: Session, barrera_id: int) -> BarreraIdentificada:
    b = db.get(BarreraIdentificada, barrera_id)
    if b is None:
        raise NotFound("No encontramos la barrera indicada.", "BARRERA_NO_ENCONTRADA")
    return b


def barrier_view(db: Session, b: BarreraIdentificada) -> dict[str, Any]:
    row = _detalle_row(db, BARRERA_MODELOS[b.tipo_barrera], "barrera_id", b.id)
    fac_ids = list(db.scalars(select(BarreraFacilitador.facilitador_id).where(BarreraFacilitador.barrera_id == b.id)))
    d = {"id": b.id, **_dump(b)}
    d["detalle"] = _dump(row, {"barrera_id"}) if row else {}
    d["facilitadores_que_la_mitigan"] = fac_ids
    d["aviso"] = "La barrera es del entorno, no de la persona."
    return d


# ============================================================================ F5
def get_facilitator(db: Session, fid: int) -> Facilitador:
    f = db.get(Facilitador, fid)
    if f is None:
        raise NotFound("No encontramos el facilitador indicado.", "FACILITADOR_NO_ENCONTRADO")
    return f


def set_links(db: Session, f: Facilitador, barrera_ids: list[int], *, reemplazar: bool = True) -> None:
    ids = set(barrera_ids)
    if ids:
        validas = set(db.scalars(select(BarreraIdentificada.id).where(BarreraIdentificada.id.in_(ids),
                                                                       BarreraIdentificada.estudiante_id == f.estudiante_id)))
        if validas != ids:
            raise Unprocessable("Algunas barreras no existen o no son de este estudiante.", "BARRERAS_INVALIDAS",
                                extra={"invalidas": sorted(ids - validas)})
    existentes = {v.barrera_id: v for v in db.scalars(select(BarreraFacilitador).where(BarreraFacilitador.facilitador_id == f.id))}
    for bid in ids - set(existentes):
        db.add(BarreraFacilitador(barrera_id=bid, facilitador_id=f.id))
    if reemplazar:
        for bid, v in existentes.items():
            if bid not in ids:
                v.soft_delete(None, "Vínculo retirado")
    db.flush()


def create_facilitator(db: Session, est: Estudiante, actor: Usuario, body) -> Facilitador:
    tipo = body.tipo_facilitador
    detalle = _validate(FACILITADOR_DETALLE_IN[tipo], body.detalle, f"el facilitador {tipo}").model_dump(exclude_unset=True)
    f = Facilitador(
        estudiante_id=est.id, tipo_facilitador=tipo, nombre_facilitador=body.nombre_facilitador.strip(),
        descripcion_detallada=body.descripcion_detallada.strip(), contextos_donde_opera=body.contextos_donde_opera,
        intensidad_impacto=body.intensidad_impacto, renovabilidad=body.renovabilidad,
        fecha_identificacion=body.fecha_identificacion or date.today(), potencial_de_uso=body.potencial_de_uso,
        registrado_por_id=actor.id,
    )
    db.add(f)
    db.flush()
    if detalle:
        db.add(FACILITADOR_MODELOS[tipo](facilitador_id=f.id, **detalle))
    set_links(db, f, body.barreras_mitigadas, reemplazar=False)
    return f


def update_facilitator(db: Session, f: Facilitador, body) -> Facilitador:
    data = body.model_dump(exclude_unset=True)
    detalle_in = data.pop("detalle", None)
    links = data.pop("barreras_mitigadas", None)
    for k, v in data.items():
        if v is None and k in ("nombre_facilitador", "descripcion_detallada", "fecha_identificacion"):
            continue
        setattr(f, k, v)
    if detalle_in is not None:
        model = FACILITADOR_MODELOS[f.tipo_facilitador]
        patch = _validate(FACILITADOR_DETALLE_PATCH[f.tipo_facilitador], detalle_in, f"el facilitador {f.tipo_facilitador}").model_dump(exclude_unset=True)
        row = _detalle_row(db, model, "facilitador_id", f.id)
        if row is None:
            db.add(model(facilitador_id=f.id, **patch))
        else:
            for k, v in patch.items():
                setattr(row, k, v)
    if links is not None:
        set_links(db, f, links, reemplazar=True)
    db.flush()
    return f


def facilitator_view(db: Session, f: Facilitador) -> dict[str, Any]:
    row = _detalle_row(db, FACILITADOR_MODELOS[f.tipo_facilitador], "facilitador_id", f.id)
    d = {"id": f.id, **_dump(f)}
    d["detalle"] = _dump(row, {"facilitador_id"}) if row else {}
    d["barreras_mitigadas"] = list(db.scalars(select(BarreraFacilitador.barrera_id).where(BarreraFacilitador.facilitador_id == f.id)))
    return d


def cross_summary(db: Session, est_id: int) -> dict[str, Any]:
    barreras = db.scalars(select(BarreraIdentificada).where(BarreraIdentificada.estudiante_id == est_id).order_by(BarreraIdentificada.id)).all()
    facs = db.scalars(select(Facilitador).where(Facilitador.estudiante_id == est_id).order_by(Facilitador.id)).all()
    links = db.scalars(select(BarreraFacilitador)).all()
    bids = {b.id for b in barreras}
    fids = {f.id for f in facs}
    por_barrera: dict[int, list[int]] = {b: [] for b in bids}
    por_fac: dict[int, list[int]] = {f: [] for f in fids}
    for lk in links:
        if lk.barrera_id in bids and lk.facilitador_id in fids:
            por_barrera[lk.barrera_id].append(lk.facilitador_id)
            por_fac[lk.facilitador_id].append(lk.barrera_id)
    fmap = {f.id: f for f in facs}
    return {
        "estudiante_id": est_id,
        "barreras": [{
            "id": b.id, "tipo_barrera": str(b.tipo_barrera), "escenario": str(b.escenario) if b.escenario else None,
            "severidad": str(b.severidad), "estado": str(b.estado), "descripcion_barrera": b.descripcion_barrera,
            "facilitadores": [{"id": i, "tipo_facilitador": str(fmap[i].tipo_facilitador), "nombre_facilitador": fmap[i].nombre_facilitador}
                              for i in por_barrera[b.id]],
        } for b in barreras],
        "facilitadores_sin_barrera": [{"id": f.id, "tipo_facilitador": str(f.tipo_facilitador), "nombre_facilitador": f.nombre_facilitador}
                                      for f in facs if not por_fac[f.id]],
        "barreras_sin_facilitador": [b.id for b in barreras if not por_barrera[b.id]],
        "totales": {"barreras": len(barreras), "facilitadores": len(facs),
                    "barreras_sin_facilitador": sum(1 for b in barreras if not por_barrera[b.id]),
                    "barreras_persistentes": sum(1 for b in barreras if b.estado == EstadoBarrera.PERSISTENTE)},
    }

