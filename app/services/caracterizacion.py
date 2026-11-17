"""F1 (caracterización, RF-12) y F2 (perfil de fortalezas, RF-13): secciones con guardado parcial, progreso, vista previa,
confirmación y versionado.

Versionado: mientras el formato esté INCOMPLETA/EN_REVISION se edita en el sitio. Si ya está COMPLETA (confirmada) y
alguien lo modifica, se crea una NUEVA versión (copia + cambio) y la anterior queda como historial. La nueva versión nace
INCOMPLETA (si edita Bienestar) o EN_REVISION (si edita el estudiante) y debe volver a confirmarse.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Unprocessable
from app.models.base import utcnow
from app.models.caracterizacion import (
    Caracterizacion,
    DatoAutonomia,
    DatoComunicacion,
    DatoPreferencia,
    DatoSensorial,
    EstrategiaAprendizaje,
    Fortaleza,
    Interes,
    PerfilFortalezas,
)
from app.models.enums import EstadoCaracterizacion, EstadoPerfil, Rol
from app.models.slice_b import FormatoComentario, HistoriaAcademica, MetaEstudiante, PerfilFortalezasEstado
from app.models.usuarios import Estudiante, Usuario
from app.services.notifications import get_notification_user_ids

# sección -> (modelo hijo, campo clave natural, relación FK, nombre legible)
F1_LISTAS = {
    "comunicacion": (DatoComunicacion, "tipo_comunicacion"),
    "sensorial": (DatoSensorial, "tipo_sensorial"),
    "autonomia": (DatoAutonomia, "contexto_autonomia"),
    "preferencias": (DatoPreferencia, "tipo_preferencia"),
}
F2_LISTAS = {
    "fortalezas": (Fortaleza, "nombre_fortaleza"),
    "intereses": (Interes, "nombre_interes"),
    "estrategias": (EstrategiaAprendizaje, "nombre_estrategia"),
    "metas": (MetaEstudiante, "descripcion"),
}
F1_OBLIGATORIAS = ["historia_academica", "comunicacion", "sensorial", "autonomia", "preferencias", "resumen"]
F1_NOMBRES = {
    "historia_academica": "Historia académica", "comunicacion": "Comunicación", "sensorial": "Perfil sensorial",
    "autonomia": "Autonomía", "preferencias": "Preferencias", "resumen": "Resumen", "autodescripcion": "En mis palabras",
}
F2_OBLIGATORIAS = ["fortalezas", "intereses", "estrategias", "metas"]
F2_NOMBRES = {"fortalezas": "Fortalezas", "intereses": "Intereses", "estrategias": "Estrategias de aprendizaje",
              "metas": "Metas", "narrativas": "Narrativas"}
F1_ESTUDIANTE = {"autodescripcion"}  # secciones de F1 que el estudiante puede escribir (su voz)

_HIST = ["trayectoria_escolar", "apoyos_previos", "experiencias_exitosas", "dificultades_previas", "otras_observaciones"]
_COLS_EXCL = {"id", "created_at", "updated_at", "deleted_at", "deleted_reason", "deleted_by_id"}


def _key(v: Any) -> str:
    return str(v).strip().lower()


def _cols(model) -> list[str]:
    return [c.key for c in model.__table__.columns if c.key not in _COLS_EXCL]


# ============================================================================ regla de servicio (ck_caracterizacion_completa)
def has_confirmed_f1(db: Session, estudiante_id: int) -> bool:
    return db.scalar(
        select(Caracterizacion.id).where(Caracterizacion.estudiante_id == estudiante_id,
                                         Caracterizacion.estado == EstadoCaracterizacion.COMPLETA).limit(1)
    ) is not None


# ============================================================================ F1
def current_f1(db: Session, estudiante_id: int) -> Caracterizacion | None:
    return db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == estudiante_id)
                     .order_by(Caracterizacion.version.desc()))


def _children(db: Session, model, fk_name: str, parent_id: int) -> list[Any]:
    return list(db.scalars(select(model).where(getattr(model, fk_name) == parent_id).order_by(model.id)).all())


def _historia(db: Session, car_id: int) -> HistoriaAcademica | None:
    return db.scalar(select(HistoriaAcademica).where(HistoriaAcademica.caracterizacion_id == car_id))


def _professional_for(db: Session, est: Estudiante, actor: Usuario) -> int:
    if str(actor.rol) == Rol.BIENESTAR:
        return actor.id
    if est.bienestar_asignado_id:
        return est.bienestar_asignado_id
    ids = get_notification_user_ids(db, "BIENESTAR")
    if not ids:
        raise Unprocessable("No hay un profesional de Bienestar disponible para acompañar este formato.", "SIN_PROFESIONAL")
    return ids[0]


def _clone_f1(db: Session, car: Caracterizacion, nuevo_estado: EstadoCaracterizacion, prof_id: int) -> Caracterizacion:
    nueva = Caracterizacion(
        estudiante_id=car.estudiante_id, fecha_caracterizacion=date.today(), profesional_responsable_id=prof_id,
        resumen_ejecutivo=car.resumen_ejecutivo, autodescripcion_estudiante=car.autodescripcion_estudiante,
        participacion_estudiante=car.participacion_estudiante, version=car.version + 1, estado=nuevo_estado,
        fecha_ultima_actualizacion=utcnow(),
    )
    db.add(nueva)
    db.flush()
    for _tname, (model, _k) in F1_LISTAS.items():
        for old in _children(db, model, "caracterizacion_id", car.id):
            db.add(model(caracterizacion_id=nueva.id, **{c: getattr(old, c) for c in _cols(model) if c != "caracterizacion_id"}))
    h = _historia(db, car.id)
    if h is not None:
        db.add(HistoriaAcademica(caracterizacion_id=nueva.id, **{c: getattr(h, c) for c in _HIST}))
    db.flush()
    return nueva


def editable_f1(db: Session, est: Estudiante, actor: Usuario) -> Caracterizacion:
    por_estudiante = str(actor.rol) == Rol.ESTUDIANTE
    car = current_f1(db, est.id)
    if car is None:
        car = Caracterizacion(
            estudiante_id=est.id, fecha_caracterizacion=date.today(), profesional_responsable_id=_professional_for(db, est, actor),
            estado=EstadoCaracterizacion.INCOMPLETA, version=1,
        )
        db.add(car)
        db.flush()
    elif car.estado == EstadoCaracterizacion.COMPLETA:
        car = _clone_f1(db, car, EstadoCaracterizacion.EN_REVISION if por_estudiante else EstadoCaracterizacion.INCOMPLETA,
                        _professional_for(db, est, actor))
    if not por_estudiante:
        car.profesional_responsable_id = actor.id
    car.fecha_ultima_actualizacion = utcnow()
    return car


def _upsert_items(db: Session, model, fk_name: str, parent_id: int, key_field: str, items: list[Any], quitar: list, actor: Usuario) -> None:
    existentes = _children(db, model, fk_name, parent_id)
    por_id = {e.id: e for e in existentes}
    por_clave = {_key(getattr(e, key_field)): e for e in existentes}
    for it in items:
        data = it.model_dump(exclude_unset=True)
        iid = data.pop("id", None)
        clave = _key(data[key_field])
        obj = por_id.get(iid) if iid is not None else por_clave.get(clave)
        if iid is not None and obj is None:
            raise Unprocessable(f"No existe el elemento {iid} en esta sección.", "ELEMENTO_NO_ENCONTRADO")
        if obj is None:
            obj = model(**{fk_name: parent_id}, **data)
            db.add(obj)
        else:
            for k, v in data.items():
                setattr(obj, k, v)
        por_clave[clave] = obj
    for q in quitar:
        obj = por_id.get(q) if isinstance(q, int) else por_clave.get(_key(q))
        if obj is not None and not obj.is_deleted:
            obj.soft_delete(actor.id, "Quitado por el usuario desde el formulario")


def save_f1_section(db: Session, est: Estudiante, actor: Usuario, seccion: str, body: Any) -> Caracterizacion:
    car = editable_f1(db, est, actor)
    if seccion in F1_LISTAS:
        model, key = F1_LISTAS[seccion]
        _upsert_items(db, model, "caracterizacion_id", car.id, key, body.items, body.quitar, actor)
    elif seccion == "historia_academica":
        h = _historia(db, car.id)
        if h is None:
            h = HistoriaAcademica(caracterizacion_id=car.id)
            db.add(h)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(h, k, (v or None))
    elif seccion == "resumen":
        car.resumen_ejecutivo = (body.resumen_ejecutivo or "").strip() or None
    elif seccion == "autodescripcion":
        car.autodescripcion_estudiante = (body.autodescripcion_estudiante or "").strip() or None
    db.flush()
    return car


def f1_progress(db: Session, car: Caracterizacion | None) -> dict[str, Any]:
    comp: dict[str, bool] = {s: False for s in F1_NOMBRES}
    if car is not None:
        for s, (model, _k) in F1_LISTAS.items():
            comp[s] = bool(_children(db, model, "caracterizacion_id", car.id))
        h = _historia(db, car.id)
        comp["historia_academica"] = bool(h and any((getattr(h, c) or "").strip() for c in _HIST))
        comp["resumen"] = bool((car.resumen_ejecutivo or "").strip())
        comp["autodescripcion"] = bool((car.autodescripcion_estudiante or "").strip())
    secciones = [{"clave": s, "nombre": F1_NOMBRES[s], "obligatoria": s in F1_OBLIGATORIAS, "completa": comp[s]} for s in F1_NOMBRES]
    hechas = sum(1 for s in F1_OBLIGATORIAS if comp[s])
    return {
        "formato": "F1", "version": car.version if car else 0, "estado": str(car.estado) if car else "INCOMPLETA",
        "porcentaje": round(100 * hechas / len(F1_OBLIGATORIAS)), "secciones": secciones,
        "faltantes": [F1_NOMBRES[s] for s in F1_OBLIGATORIAS if not comp[s]],
        "puede_confirmar": car is not None and hechas == len(F1_OBLIGATORIAS) and car.estado != EstadoCaracterizacion.COMPLETA,
    }


def comentarios(db: Session, estudiante_id: int, formato: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(FormatoComentario).where(FormatoComentario.estudiante_id == estudiante_id,
                                                      FormatoComentario.formato == formato).order_by(FormatoComentario.id)).all()
    return [{"id": c.id, "seccion": c.seccion, "texto": c.texto, "autor_rol": c.autor_rol,
             "created_at": c.created_at.isoformat()} for c in rows]


def add_comment(db: Session, est: Estudiante, actor: Usuario, formato: str, seccion: str, texto: str) -> FormatoComentario:
    c = FormatoComentario(estudiante_id=est.id, formato=formato, seccion=seccion, autor_id=actor.id,
                          autor_rol=str(actor.rol), texto=texto.strip())
    db.add(c)
    db.flush()
    return c


def _item(model_obj, extra_excl: set[str] | None = None) -> dict[str, Any]:
    ex = _COLS_EXCL | (extra_excl or set())
    return {c.key: getattr(model_obj, c.key) for c in model_obj.__table__.columns if c.key not in ex}


def f1_view(db: Session, est_id: int, car: Caracterizacion | None) -> dict[str, Any]:
    base: dict[str, Any] = {"estudiante_id": est_id, "formato": "F1", "existe": car is not None}
    if car is None:
        base.update({"id": None, "version": 0, "estado": "INCOMPLETA", "historia_academica": None, "comunicacion": [],
                     "sensorial": [], "autonomia": [], "preferencias": [], "resumen_ejecutivo": None,
                     "autodescripcion_estudiante": None})
    else:
        h = _historia(db, car.id)
        base.update({
            "id": car.id, "version": car.version, "estado": str(car.estado),
            "fecha_caracterizacion": car.fecha_caracterizacion.isoformat(),
            "fecha_ultima_actualizacion": car.fecha_ultima_actualizacion.isoformat() if car.fecha_ultima_actualizacion else None,
            "profesional_responsable_id": car.profesional_responsable_id,
            "historia_academica": {c: getattr(h, c) for c in _HIST} if h else None,
            **{s: [_item(o, {"caracterizacion_id"}) for o in _children(db, m, "caracterizacion_id", car.id)]
               for s, (m, _k) in F1_LISTAS.items()},
            "resumen_ejecutivo": car.resumen_ejecutivo, "autodescripcion_estudiante": car.autodescripcion_estudiante,
        })
    base["comentarios"] = comentarios(db, est_id, "F1")
    return base


def f1_preview(db: Session, est_id: int, car: Caracterizacion | None) -> dict[str, Any]:
    v = f1_view(db, est_id, car)
    bloques = []
    h = v["historia_academica"] or {}
    lineas = [f"{t}: {h[k]}" for k, t in (("trayectoria_escolar", "Trayectoria"), ("apoyos_previos", "Apoyos previos"),
                                           ("experiencias_exitosas", "Lo que le ha funcionado"),
                                           ("dificultades_previas", "Dificultades previas")) if h.get(k)]
    if lineas:
        bloques.append({"titulo": "Historia académica", "lineas": lineas})
    if v["comunicacion"]:
        bloques.append({"titulo": "Cómo se comunica", "lineas": [
            f"{c['tipo_comunicacion']}: {c['descripcion']}" + (f" Le ayuda: {c['estrategias_favorables']}" if c.get("estrategias_favorables") else "")
            for c in v["comunicacion"]]})
    if v["sensorial"]:
        bloques.append({"titulo": "Perfil sensorial", "lineas": [
            f"{str(s['tipo_sensorial']).capitalize()}"
            + (" (más sensible de lo habitual)" if s.get("hipersensibilidad") else "")
            + (" (menos sensible de lo habitual)" if s.get("hiposensibilidad") else "")
            + (f": {s['descripcion_experiencia']}" if s.get("descripcion_experiencia") else "") for s in v["sensorial"]]})
    if v["autonomia"]:
        bloques.append({"titulo": "Autonomía", "lineas": [
            f"{a['contexto_autonomia']}: autonomía {str(a['nivel_autonomia']).lower()}" for a in v["autonomia"]]})
    if v["preferencias"]:
        bloques.append({"titulo": "Preferencias", "lineas": [f"{p['tipo_preferencia']}: {p['descripcion']}" for p in v["preferencias"]]})
    if v["resumen_ejecutivo"]:
        bloques.append({"titulo": "Resumen del profesional", "lineas": [v["resumen_ejecutivo"]]})
    if v["autodescripcion_estudiante"]:
        bloques.append({"titulo": "En sus palabras", "lineas": [v["autodescripcion_estudiante"]]})
    return {
        "estudiante_id": est_id, "formato": "F1", "version": v["version"], "estado": v["estado"], "bloques": bloques,
        "aviso": "Este perfil describe cómo aprende y qué apoyos le sirven. Las barreras son del entorno, no de la persona.",
        "progreso": f1_progress(db, car),
    }


def confirm_f1(db: Session, car: Caracterizacion | None, actor: Usuario) -> Caracterizacion:
    prog = f1_progress(db, car)
    if car is None or prog["faltantes"]:
        raise Conflict("Faltan secciones obligatorias por completar antes de confirmar la caracterización (F1).",
                       "FORMATO_INCOMPLETO", extra={"faltantes": prog["faltantes"]})
    if car.estado == EstadoCaracterizacion.COMPLETA:
        raise Conflict("Esta versión de la caracterización ya está confirmada.", "FORMATO_YA_CONFIRMADO")
    car.estado = EstadoCaracterizacion.COMPLETA
    car.fecha_ultima_actualizacion = utcnow()
    car.profesional_responsable_id = actor.id
    return car


# ============================================================================ F2
def current_f2(db: Session, estudiante_id: int) -> PerfilFortalezas | None:
    return db.scalar(select(PerfilFortalezas).where(PerfilFortalezas.estudiante_id == estudiante_id,
                                                    PerfilFortalezas.estado == EstadoPerfil.ACTIVO)
                     .order_by(PerfilFortalezas.version.desc()))


def f2_estado_row(db: Session, perfil_id: int) -> PerfilFortalezasEstado | None:
    return db.scalar(select(PerfilFortalezasEstado).where(PerfilFortalezasEstado.perfil_fortalezas_id == perfil_id))


def f2_estado(db: Session, perfil: PerfilFortalezas | None) -> str:
    if perfil is None:
        return "INCOMPLETA"
    r = f2_estado_row(db, perfil.id)
    return str(r.estado) if r else "INCOMPLETA"


def _clone_f2(db: Session, p: PerfilFortalezas, estado: EstadoCaracterizacion, prof_id: int) -> PerfilFortalezas:
    nuevo = PerfilFortalezas(
        estudiante_id=p.estudiante_id, fecha_elaboracion=date.today(), profesional_responsable_id=prof_id,
        narrativa_fortalezas=p.narrativa_fortalezas, narrativa_intereses=p.narrativa_intereses,
        narrativa_estrategias=p.narrativa_estrategias, version=p.version + 1, estado=EstadoPerfil.ACTIVO,
    )
    db.add(nuevo)
    db.flush()
    for _s, (model, _k) in F2_LISTAS.items():
        for old in _children(db, model, "perfil_fortalezas_id", p.id):
            db.add(model(perfil_fortalezas_id=nuevo.id, **{c: getattr(old, c) for c in _cols(model) if c != "perfil_fortalezas_id"}))
    p.estado = EstadoPerfil.ARCHIVADO
    db.add(PerfilFortalezasEstado(perfil_fortalezas_id=nuevo.id, estado=estado))
    db.flush()
    return nuevo


def editable_f2(db: Session, est: Estudiante, actor: Usuario) -> PerfilFortalezas:
    por_estudiante = str(actor.rol) == Rol.ESTUDIANTE
    p = current_f2(db, est.id)
    if p is None:
        p = PerfilFortalezas(estudiante_id=est.id, fecha_elaboracion=date.today(),
                             profesional_responsable_id=_professional_for(db, est, actor), version=1)
        db.add(p)
        db.flush()
        db.add(PerfilFortalezasEstado(perfil_fortalezas_id=p.id, estado=EstadoCaracterizacion.INCOMPLETA))
        db.flush()
    elif f2_estado(db, p) == "COMPLETA":
        p = _clone_f2(db, p, EstadoCaracterizacion.EN_REVISION if por_estudiante else EstadoCaracterizacion.INCOMPLETA,
                      _professional_for(db, est, actor))
    elif f2_estado_row(db, p.id) is None:
        db.add(PerfilFortalezasEstado(perfil_fortalezas_id=p.id, estado=EstadoCaracterizacion.INCOMPLETA))
    if not por_estudiante:
        p.profesional_responsable_id = actor.id
    p.updated_at = utcnow()
    return p


def save_f2_section(db: Session, est: Estudiante, actor: Usuario, seccion: str, body: Any) -> PerfilFortalezas:
    p = editable_f2(db, est, actor)
    if seccion in F2_LISTAS:
        model, key = F2_LISTAS[seccion]
        _upsert_items(db, model, "perfil_fortalezas_id", p.id, key, body.items, body.quitar, actor)
    else:  # narrativas
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(p, k, (v or "").strip() or None)
    db.flush()
    return p


def f2_progress(db: Session, p: PerfilFortalezas | None) -> dict[str, Any]:
    comp = {s: False for s in F2_NOMBRES}
    if p is not None:
        for s, (model, _k) in F2_LISTAS.items():
            comp[s] = bool(_children(db, model, "perfil_fortalezas_id", p.id))
        comp["narrativas"] = any((getattr(p, c) or "").strip() for c in ("narrativa_fortalezas", "narrativa_intereses", "narrativa_estrategias"))
    estado = f2_estado(db, p)
    hechas = sum(1 for s in F2_OBLIGATORIAS if comp[s])
    return {
        "formato": "F2", "version": p.version if p else 0, "estado": estado,
        "porcentaje": round(100 * hechas / len(F2_OBLIGATORIAS)),
        "secciones": [{"clave": s, "nombre": F2_NOMBRES[s], "obligatoria": s in F2_OBLIGATORIAS, "completa": comp[s]} for s in F2_NOMBRES],
        "faltantes": [F2_NOMBRES[s] for s in F2_OBLIGATORIAS if not comp[s]],
        "puede_confirmar": p is not None and hechas == len(F2_OBLIGATORIAS) and estado != "COMPLETA",
    }


def f2_view(db: Session, est_id: int, p: PerfilFortalezas | None) -> dict[str, Any]:
    base: dict[str, Any] = {"estudiante_id": est_id, "formato": "F2", "existe": p is not None}
    if p is None:
        base.update({"id": None, "version": 0, "estado": "INCOMPLETA", "fortalezas": [], "intereses": [], "estrategias": [],
                     "metas": [], "narrativas": {"narrativa_fortalezas": None, "narrativa_intereses": None, "narrativa_estrategias": None}})
    else:
        base.update({
            "id": p.id, "version": p.version, "estado": f2_estado(db, p), "fecha_elaboracion": p.fecha_elaboracion.isoformat(),
            "profesional_responsable_id": p.profesional_responsable_id,
            **{s: [_item(o, {"perfil_fortalezas_id"}) for o in _children(db, m, "perfil_fortalezas_id", p.id)]
               for s, (m, _k) in F2_LISTAS.items()},
            "narrativas": {c: getattr(p, c) for c in ("narrativa_fortalezas", "narrativa_intereses", "narrativa_estrategias")},
        })
    base["comentarios"] = comentarios(db, est_id, "F2")
    return base


def f2_preview(db: Session, est_id: int, p: PerfilFortalezas | None) -> dict[str, Any]:
    v = f2_view(db, est_id, p)
    bloques = []
    if v["fortalezas"]:
        bloques.append({"titulo": "Fortalezas", "lineas": [f"{f['nombre_fortaleza']}: {f['descripcion_detallada']}" for f in v["fortalezas"]]})
    if v["intereses"]:
        bloques.append({"titulo": "Intereses", "lineas": [f"{i['nombre_interes']}: {i['descripcion']}" for i in v["intereses"]]})
    if v["estrategias"]:
        bloques.append({"titulo": "Cómo aprende mejor", "lineas": [f"{e['nombre_estrategia']}: {e['descripcion']}" for e in v["estrategias"]]})
    if v["metas"]:
        bloques.append({"titulo": "Metas", "lineas": [f"{m['descripcion']}" + (f" ({m['plazo']})" if m.get("plazo") else "") for m in v["metas"]]})
    for k, t in (("narrativa_fortalezas", "Sobre sus fortalezas"), ("narrativa_intereses", "Sobre sus intereses"),
                 ("narrativa_estrategias", "Sobre sus estrategias")):
        if v["narrativas"].get(k):
            bloques.append({"titulo": t, "lineas": [v["narrativas"][k]]})
    return {"estudiante_id": est_id, "formato": "F2", "version": v["version"], "estado": v["estado"], "bloques": bloques,
            "progreso": f2_progress(db, p)}


def confirm_f2(db: Session, p: PerfilFortalezas | None, actor: Usuario) -> PerfilFortalezas:
    prog = f2_progress(db, p)
    if p is None or prog["faltantes"]:
        raise Conflict("Faltan secciones obligatorias por completar antes de confirmar el perfil de fortalezas (F2).",
                       "FORMATO_INCOMPLETO", extra={"faltantes": prog["faltantes"]})
    if prog["estado"] == "COMPLETA":
        raise Conflict("Esta versión del perfil de fortalezas ya está confirmada.", "FORMATO_YA_CONFIRMADO")
    r = f2_estado_row(db, p.id)
    if r is None:
        r = PerfilFortalezasEstado(perfil_fortalezas_id=p.id)
        db.add(r)
    r.estado = EstadoCaracterizacion.COMPLETA
    r.confirmado_por_id = actor.id
    r.confirmado_at = utcnow()
    p.profesional_responsable_id = actor.id
    return p
