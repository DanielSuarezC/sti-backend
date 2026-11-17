"""Trayectoria academica (D9 / M8): semestres, 9 dimensiones, hitos, resumen y proyeccion de necesidades.

* `TRAYECTORIA_ACADEMICA` = un semestre del estudiante; sus 9 dimensiones (ERD §3.55-3.63) son tablas de una fila por
  trayectoria (se crean al primer PATCH de la seccion, con los valores por defecto del modelo).
* `proyectar_necesidades` calcula las necesidades del siguiente semestre a partir del plan de estudios del programa:
  1. `ASIGNATURA` (programa + `semestre_plan` + `creditos` + `es_practica` + `escenario_predominante`);
  2. `PROGRAMA_ACADEMICO` (`semestre_practicas`, `duracion_semestres`, `total_creditos`);
  3. (opcional) parametro del sistema JSON `plan_estudios`: ``{"<programa_id>": {"<nivel_semestre>": {"practicas": bool,
     "pasantias": bool, "trabajo_grado": bool, "creditos": int, "notas": str}}}``. No existe por defecto: se crea
     desde Administracion (`PARAMETRO_SISTEMA.clave = "plan_estudios"`, tipo JSON) cuando el programa no carga asignaturas.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.academico import Asignatura, CalendarioAcademico, Matricula, ProgramaAcademico
from app.models.enums import Escenario
from app.models.trayectoria import (
    Acceso,
    Aprendizaje,
    Autonomia,
    BienestarTrayectoria,
    Graduacion,
    HitoTrayectoria,
    Participacion,
    Permanencia,
    Progresion,
    TransicionProfesional,
    TrayectoriaAcademica,
)
from app.models.usuarios import Estudiante
from app.services.params import get_param

#: dimension (API) -> (atributo de relacion en TrayectoriaAcademica, modelo)
DIMENSIONES: dict[str, tuple[str, type]] = {
    "ACCESO": ("acceso", Acceso),
    "PARTICIPACION": ("participacion", Participacion),
    "APRENDIZAJE": ("aprendizaje", Aprendizaje),
    "BIENESTAR": ("bienestar", BienestarTrayectoria),
    "AUTONOMIA": ("autonomia", Autonomia),
    "PERMANENCIA": ("permanencia", Permanencia),
    "PROGRESION": ("progresion", Progresion),
    "GRADUACION": ("graduacion", Graduacion),
    "TRANSICION_PROFESIONAL": ("transicion", TransicionProfesional),
}
_DECIMALES = {"asistencia_promedio", "calificaciones_promedio"}
_COLUMNAS_BASE = {"id", "created_at", "updated_at", "deleted_at", "deleted_reason", "deleted_by_id", "trayectoria_id"}

_SEM_RE = re.compile(r"^(\d{4})-(I|II)$")


# ----------------------------------------------------------------------------- semestres
def siguiente_semestre(semestre: str, n: int = 1) -> str:
    """``siguiente_semestre("2026-II") -> "2027-I"``; con ``n`` avanza varios periodos."""
    m = _SEM_RE.match(semestre or "")
    if not m:
        raise Unprocessable("El semestre debe tener el formato AAAA-I o AAAA-II (por ejemplo 2026-II).", "SEMESTRE_INVALIDO")
    idx = int(m.group(1)) * 2 + (0 if m.group(2) == "I" else 1) + n
    return f"{idx // 2}-{'I' if idx % 2 == 0 else 'II'}"


def _num(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def _serializar_valor(v: Any) -> Any:
    v = _num(v)
    return v.isoformat() if isinstance(v, date) else v


# ----------------------------------------------------------------------------- trayectoria
def get_trayectoria(db: Session, estudiante_id: int, semestre: str) -> TrayectoriaAcademica | None:
    return db.scalar(
        select(TrayectoriaAcademica).where(
            TrayectoriaAcademica.estudiante_id == estudiante_id, TrayectoriaAcademica.semestre_academico == semestre
        )
    )


def get_trayectoria_or_404(db: Session, estudiante_id: int, semestre: str) -> TrayectoriaAcademica:
    t = get_trayectoria(db, estudiante_id, semestre)
    if t is None:
        raise NotFound(f"No hay trayectoria registrada para el semestre {semestre}.", "TRAYECTORIA_NO_ENCONTRADA")
    return t


def listar_trayectorias(db: Session, estudiante_id: int) -> list[TrayectoriaAcademica]:
    return list(
        db.scalars(
            select(TrayectoriaAcademica)
            .where(TrayectoriaAcademica.estudiante_id == estudiante_id)
            .order_by(TrayectoriaAcademica.semestre_academico)
        )
    )


def _fila_dimension(tray: TrayectoriaAcademica, dimension: str):
    attr, _model = DIMENSIONES[dimension]
    filas = getattr(tray, attr)
    return filas[0] if filas else None


def serializar_dimension(fila) -> dict[str, Any] | None:
    if fila is None:
        return None
    out: dict[str, Any] = {}
    for col in fila.__table__.columns:
        if col.name in _COLUMNAS_BASE:
            continue
        out[col.name] = _serializar_valor(getattr(fila, col.name))
    return out


def serializar_trayectoria(tray: TrayectoriaAcademica) -> dict[str, Any]:
    return {
        "id": tray.id,
        "estudiante_id": tray.estudiante_id,
        "semestre_academico": tray.semestre_academico,
        "fecha_inicio_semestre": tray.fecha_inicio_semestre,
        "fecha_fin_semestre": tray.fecha_fin_semestre,
        "asignaturas_inscritas": tray.asignaturas_inscritas,
        "asignaturas_completadas": tray.asignaturas_completadas,
        "creditos_aprobados": tray.creditos_aprobados,
        "promedio_academico": _num(tray.promedio_academico),
        "dimensiones": {d: serializar_dimension(_fila_dimension(tray, d)) for d in DIMENSIONES},
    }


def _fecha_inicio_por_calendario(db: Session, est: Estudiante, semestre: str) -> date | None:
    """Inicio del semestre segun el calendario academico (el del programa; si no, el institucional)."""
    for programa_id in (est.programa_id, None):
        cal = db.scalar(
            select(CalendarioAcademico).where(
                CalendarioAcademico.semestre_academico == semestre,
                CalendarioAcademico.programa_id.is_(None) if programa_id is None
                else CalendarioAcademico.programa_id == programa_id,
            )
        )
        if cal is not None:
            return cal.fecha_inicio
    return None


def aplicar_dimension(db: Session, tray: TrayectoriaAcademica, dimension: str, datos: dict[str, Any]):
    """Crea (si no existe) y actualiza parcialmente una dimension. `datos` ya validado (solo claves enviadas)."""
    attr, modelo = DIMENSIONES[dimension]
    fila = _fila_dimension(tray, dimension)
    if fila is None:
        fila = modelo(trayectoria_id=tray.id)
        db.add(fila)
    cols = {c.name for c in modelo.__table__.columns} - _COLUMNAS_BASE
    for k, v in datos.items():
        if k not in cols:
            continue
        if v is None and not modelo.__table__.columns[k].nullable:
            continue  # un null no borra campos obligatorios: se conserva el valor
        if k in _DECIMALES and v is not None:
            v = Decimal(str(v))
        setattr(fila, k, v)
    db.flush()
    db.refresh(tray, attribute_names=[attr])
    return fila


def _datos_dimensiones(dimensiones: BaseModel | dict | None) -> dict[str, dict[str, Any]]:
    """{dimension: solo los campos enviados}, con los enums como texto. Acepta `DimensionesIn` o un dict validado."""
    if dimensiones is None:
        return {}
    crudo = dimensiones.model_dump(exclude_unset=True) if isinstance(dimensiones, BaseModel) else dict(dimensiones)
    out: dict[str, dict[str, Any]] = {}
    for nombre, datos in crudo.items():
        if nombre in DIMENSIONES and datos is not None:
            out[nombre] = {k: (v.value if isinstance(v, Enum) else v) for k, v in datos.items()}
    return out


def _validar_fechas_y_coherencia(tray: TrayectoriaAcademica) -> None:
    if tray.fecha_fin_semestre is not None and tray.fecha_fin_semestre < tray.fecha_inicio_semestre:
        raise Unprocessable("La fecha de fin del semestre no puede ser anterior a la de inicio.", "FECHAS_INVALIDAS")
    if tray.asignaturas_inscritas is not None and tray.asignaturas_completadas is not None \
            and tray.asignaturas_completadas > tray.asignaturas_inscritas:
        raise Unprocessable("Las asignaturas completadas no pueden superar las inscritas.", "ASIGNATURAS_INCOHERENTES")


def crear_trayectoria(db: Session, est: Estudiante, body, actor) -> TrayectoriaAcademica:
    semestre = body.semestre_academico
    if get_trayectoria(db, est.id, semestre) is not None:
        raise Conflict(f"Ya existe la trayectoria del semestre {semestre}. Edítela en lugar de crear otra.",
                       "TRAYECTORIA_DUPLICADA")
    inicio = body.fecha_inicio_semestre or _fecha_inicio_por_calendario(db, est, semestre)
    if inicio is None:
        raise Unprocessable(
            "Indique la fecha de inicio del semestre (no hay calendario académico cargado para ese semestre).",
            "FECHA_INICIO_REQUERIDA",
        )
    tray = TrayectoriaAcademica(
        estudiante_id=est.id, semestre_academico=semestre, fecha_inicio_semestre=inicio,
        fecha_fin_semestre=body.fecha_fin_semestre, asignaturas_inscritas=body.asignaturas_inscritas,
        asignaturas_completadas=body.asignaturas_completadas, creditos_aprobados=body.creditos_aprobados,
        promedio_academico=Decimal(str(body.promedio_academico)) if body.promedio_academico is not None else None,
    )
    _validar_fechas_y_coherencia(tray)
    db.add(tray)
    db.flush()
    for nombre, datos in _datos_dimensiones(body.dimensiones).items():
        aplicar_dimension(db, tray, nombre, datos)
    return tray


def actualizar_trayectoria(db: Session, tray: TrayectoriaAcademica, body) -> TrayectoriaAcademica:
    datos = body.model_dump(exclude_unset=True, exclude={"dimensiones"})
    for k, v in datos.items():
        if k == "promedio_academico" and v is not None:
            v = Decimal(str(v))
        if v is None and k == "fecha_inicio_semestre":
            continue
        setattr(tray, k, v)
    _validar_fechas_y_coherencia(tray)
    db.flush()
    for nombre, d in _datos_dimensiones(getattr(body, "dimensiones", None)).items():
        aplicar_dimension(db, tray, nombre, d)
    db.flush()
    return tray


def crear_borrador_trayectoria(db: Session, est: Estudiante, semestre: str, anteriores: list[TrayectoriaAcademica]):
    """Trayectoria del semestre que se cierra, pre-llenada con lo que ya sabe el sistema (matricula y calendario)."""
    mat = db.scalar(select(Matricula).where(Matricula.estudiante_id == est.id, Matricula.semestre_academico == semestre))
    inicio = _fecha_inicio_por_calendario(db, est, semestre) or (mat.fecha_matricula if mat else date.today())
    tray = TrayectoriaAcademica(
        estudiante_id=est.id, semestre_academico=semestre, fecha_inicio_semestre=inicio,
        asignaturas_inscritas=mat.numero_asignaturas if mat else None,
    )
    db.add(tray)
    db.flush()
    prog = est.programa
    cursados = len(anteriores) + 1
    aplicar_dimension(db, tray, "PERMANENCIA", {"continua_matriculado": True})
    progresion: dict[str, Any] = {"semestres_completados": cursados}
    if prog is not None and prog.duracion_semestres:
        progresion["avance_plan_estudios_porcentaje"] = min(100, round(100 * cursados / prog.duracion_semestres))
    aplicar_dimension(db, tray, "PROGRESION", progresion)
    return tray


# ----------------------------------------------------------------------------- resumen y proyeccion
def _nivel_actual(est: Estudiante, trays: list[TrayectoriaAcademica]) -> int:
    return est.semestre_actual or len(trays)


def proyectar_necesidades(db: Session, est: Estudiante, nivel_destino: int | None = None) -> dict[str, Any]:
    """Necesidades del semestre `nivel_destino` (por defecto el siguiente al actual) segun el plan de estudios."""
    trays = listar_trayectorias(db, est.id)
    nivel = nivel_destino or (_nivel_actual(est, trays) + 1)
    prog: ProgramaAcademico | None = est.programa
    asignaturas: list[dict[str, Any]] = []
    fuente = "SIN_DATOS"
    if prog is not None:
        rows = db.scalars(
            select(Asignatura).where(Asignatura.programa_id == prog.id, Asignatura.semestre_plan == nivel)
            .order_by(Asignatura.codigo)
        ).all()
        asignaturas = [
            {"asignatura_id": a.id, "codigo": a.codigo, "nombre": a.nombre, "creditos": a.creditos,
             "es_practica": a.es_practica,
             "escenario_predominante": str(a.escenario_predominante) if a.escenario_predominante else None}
            for a in rows
        ]
        if asignaturas:
            fuente = "ASIGNATURAS"
    param: dict[str, Any] = {}
    plan_estudios = get_param(db, "plan_estudios") or {}
    if isinstance(plan_estudios, dict) and prog is not None:
        por_programa = plan_estudios.get(str(prog.id)) or {}
        param = por_programa.get(str(nivel)) or {}
        if param and fuente == "SIN_DATOS":
            fuente = "PARAMETRO"
    es_practicas = bool(
        (prog is not None and prog.semestre_practicas == nivel) or param.get("practicas")
        or any(a["es_practica"] for a in asignaturas)
    )
    if prog is not None and prog.semestre_practicas and fuente == "SIN_DATOS":
        fuente = "PROGRAMA"
    necesidades: list[dict[str, Any]] = []
    if es_practicas:
        necesidades.append({
            "tipo": "PRACTICAS", "semestre_nivel": nivel,
            "escenarios_sugeridos": [Escenario.PRACTICA_CLINICA.value, Escenario.PRACTICA_SALUD_PUBLICA.value],
            "descripcion": "El semestre incluye prácticas: revisar el plan para los escenarios de práctica clínica o de "
                           "salud pública (transporte, rotaciones, tutor de campo, anticipación de normas del servicio).",
        })
    if param.get("pasantias"):
        necesidades.append({"tipo": "PASANTIAS", "semestre_nivel": nivel, "escenarios_sugeridos": [Escenario.PASANTIAS.value],
                            "descripcion": "El semestre incluye pasantía: anticipar el entorno laboral y los apoyos."})
    if param.get("trabajo_grado"):
        necesidades.append({"tipo": "TRABAJO_GRADO", "semestre_nivel": nivel, "escenarios_sugeridos": [],
                            "descripcion": "El semestre incluye trabajo de grado: acordar acompañamiento y tiempos."})
    creditos = sum(a["creditos"] or 0 for a in asignaturas) or param.get("creditos")
    return {
        "nivel_semestre": nivel, "fuente": fuente, "asignaturas": asignaturas, "creditos_previstos": creditos,
        "necesidades": necesidades, "notas_plan_estudios": param.get("notas"),
    }


def proyeccion_graduacion(db: Session, est: Estudiante) -> dict[str, Any]:
    trays = listar_trayectorias(db, est.id)
    prog = est.programa
    nivel = _nivel_actual(est, trays)
    creditos = sum(t.creditos_aprobados or 0 for t in trays)
    out: dict[str, Any] = {
        "semestres_registrados": len(trays), "nivel_semestre_actual": nivel or None, "creditos_aprobados_total": creditos,
        "duracion_semestres_programa": prog.duracion_semestres if prog else None,
        "creditos_programa": prog.total_creditos if prog else None,
        "semestres_restantes": None, "semestre_estimado_graduacion": None, "avance_creditos_porcentaje": None,
    }
    if prog is not None and prog.total_creditos:
        out["avance_creditos_porcentaje"] = min(100, round(100 * creditos / prog.total_creditos))
    if prog is not None and prog.duracion_semestres and nivel:
        restantes = max(prog.duracion_semestres - nivel, 0)
        out["semestres_restantes"] = restantes
        if trays:
            out["semestre_estimado_graduacion"] = siguiente_semestre(trays[-1].semestre_academico, restantes)
    return out


def estado_permanencia(db: Session, est: Estudiante) -> dict[str, Any] | None:
    trays = listar_trayectorias(db, est.id)
    for t in reversed(trays):
        fila = _fila_dimension(t, "PERMANENCIA")
        if fila is not None:
            return {
                "semestre_academico": t.semestre_academico, "continua_matriculado": fila.continua_matriculado,
                "riesgo_desersion": str(fila.riesgo_desersion),
            }
    return None


def resumen_trayectoria(db: Session, est: Estudiante) -> dict[str, Any]:
    trays = listar_trayectorias(db, est.id)
    proy = proyeccion_graduacion(db, est)
    nec = proyectar_necesidades(db, est)
    return {
        "semestres_cursados": len(trays),
        "creditos_aprobados": proy["creditos_aprobados_total"],
        "estado_permanencia": estado_permanencia(db, est),
        "proyeccion_graduacion": proy,
        "necesidades_siguiente_semestre": nec,
        "ultimo_semestre": trays[-1].semestre_academico if trays else None,
    }


# ----------------------------------------------------------------------------- hitos
def serializar_hito(h: HitoTrayectoria, trays: dict[int, str] | None = None) -> dict[str, Any]:
    return {
        "id": h.id, "estudiante_id": h.estudiante_id, "trayectoria_id": h.trayectoria_id,
        "semestre_academico": (trays or {}).get(h.trayectoria_id) if h.trayectoria_id else None,
        "tipo_hito": str(h.tipo_hito), "fecha_hito": h.fecha_hito, "descripcion": h.descripcion,
        "registrado_por_id": h.registrado_por_id,
    }


def listar_hitos(db: Session, estudiante_id: int) -> list[dict[str, Any]]:
    trays = {t.id: t.semestre_academico for t in listar_trayectorias(db, estudiante_id)}
    hitos = db.scalars(
        select(HitoTrayectoria).where(HitoTrayectoria.estudiante_id == estudiante_id)
        .order_by(HitoTrayectoria.fecha_hito, HitoTrayectoria.id)
    ).all()
    return [serializar_hito(h, trays) for h in hitos]


def crear_hito(db: Session, est: Estudiante, body, actor) -> HitoTrayectoria:
    tray_id = None
    if body.semestre_academico:
        tray_id = get_trayectoria_or_404(db, est.id, body.semestre_academico).id
    h = HitoTrayectoria(
        estudiante_id=est.id, trayectoria_id=tray_id, tipo_hito=body.tipo_hito, fecha_hito=body.fecha_hito,
        descripcion=body.descripcion, registrado_por_id=actor.id if actor else None,
    )
    db.add(h)
    db.flush()
    return h


def get_hito_or_404(db: Session, estudiante_id: int, hito_id: int) -> HitoTrayectoria:
    h = db.get(HitoTrayectoria, hito_id)
    if h is None or h.estudiante_id != estudiante_id:
        raise NotFound("No encontramos ese hito de trayectoria.", "HITO_NO_ENCONTRADO")
    return h
