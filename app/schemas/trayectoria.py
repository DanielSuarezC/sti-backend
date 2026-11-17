"""Schemas de la trayectoria academica (D9), los hitos (M8) y el F10 con sus tres componentes (slice C3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    BalanceVidaEstudio,
    EstadoLaboral,
    EstadoTrabajoFinal,
    IndependenciaTareas,
    NivelBajoMedioAlto,
    NivelBMA,
    ParticipacionClase,
    Satisfaccion,
    TipoHito,
    TrabajoColaborativo,
)

SEMESTRE_PATTERN = r"^\d{4}-(I|II)$"
def _nota():
    return Field(default=None, max_length=4000)


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- las 9 dimensiones (todas parciales)
class DimAcceso(_Estricto):
    puede_ingresar_aulas: bool | None = None
    puede_usar_biblioteca: bool | None = None
    puede_usar_laboratorios: bool | None = None
    puede_acceder_plataforma: bool | None = None
    puede_usar_servicios_bienestar: bool | None = None
    barreras_acceso_identificadas: str | None = _nota()
    ajustes_acceso_implementados: str | None = _nota()


class DimParticipacion(_Estricto):
    asistencia_promedio: float | None = Field(default=None, ge=0, le=100)
    participacion_clase: ParticipacionClase | None = None
    actividades_extracurriculares: int | None = Field(default=None, ge=0, le=100)
    trabajo_colaborativo: TrabajoColaborativo | None = None
    interaccion_pares: str | None = _nota()
    liderazgo_grupos: bool | None = None


class DimAprendizaje(_Estricto):
    demuestra_competencias: bool | None = None
    calificaciones_promedio: float | None = Field(default=None, ge=0, le=5)
    asignaturas_aprobadas_porcentaje: int | None = Field(default=None, ge=0, le=100)
    necesidad_tutoria: bool | None = None
    mejora_academica: str | None = _nota()
    aprendizajes_significativos: str | None = _nota()


class DimBienestar(_Estricto):
    percepcion_bienestar: NivelBMA | None = None
    ansiedad_nivel: NivelBMA | None = None
    depresion_indicadores: bool | None = None
    siente_pertenencia: bool | None = None
    seguridad_percibida: NivelBMA | None = None
    apoyo_socioafectivo: str | None = _nota()
    balance_vida_estudio: BalanceVidaEstudio | None = None


class DimAutonomia(_Estricto):
    gestiona_su_agenda: bool | None = None
    solicita_apoyos_autonomamente: bool | None = None
    autorregulacion: NivelBMA | None = None
    independencia_tareas_academicas: IndependenciaTareas | None = None
    capacidad_resolucion_problemas: NivelBMA | None = None
    incremento_autonomia: str | None = _nota()


class DimPermanencia(_Estricto):
    continua_matriculado: bool | None = None
    riesgo_desersion: NivelBajoMedioAlto | None = None
    factores_riesgo: str | None = _nota()
    factores_proteccion: str | None = _nota()
    plan_retencion: str | None = _nota()
    cambios_circunstancias: str | None = _nota()


class DimProgresion(_Estricto):
    semestres_completados: int | None = Field(default=None, ge=0, le=30)
    avance_plan_estudios_porcentaje: int | None = Field(default=None, ge=0, le=100)
    creditosfaltantes: int | None = Field(default=None, ge=0, le=400)  # nombre del ERD (§3.61)
    asignaturas_pendientes: int | None = Field(default=None, ge=0, le=200)
    tiempo_estimado_graduacion: str | None = Field(default=None, max_length=50)
    probabilidad_graduacion: NivelBMA | None = None


class DimGraduacion(_Estricto):
    ha_graduado: bool | None = None
    fecha_graduacion: date | None = None
    grado_obtenido: str | None = Field(default=None, max_length=100)
    estado_trabajofinal_tesis: EstadoTrabajoFinal | None = None
    satisfaccion_formacion: Satisfaccion | None = None
    logros_academicos: str | None = _nota()


class DimTransicionProfesional(_Estricto):
    experiencia_practica_laboral: bool | None = None
    horas_practica_laboral: int | None = Field(default=None, ge=0, le=20000)
    sector_interes_profesional: str | None = Field(default=None, max_length=255)
    capacidades_laborales: str | None = _nota()
    necesidades_apoyo_laboral: str | None = _nota()
    ajustes_laborales_identificados: str | None = _nota()
    estado_laboral_actual: EstadoLaboral | None = None
    satisfaccion_laboral: Satisfaccion | None = None


DIMENSION_SCHEMAS: dict[str, type[BaseModel]] = {
    "ACCESO": DimAcceso,
    "PARTICIPACION": DimParticipacion,
    "APRENDIZAJE": DimAprendizaje,
    "BIENESTAR": DimBienestar,
    "AUTONOMIA": DimAutonomia,
    "PERMANENCIA": DimPermanencia,
    "PROGRESION": DimProgresion,
    "GRADUACION": DimGraduacion,
    "TRANSICION_PROFESIONAL": DimTransicionProfesional,
}
DimensionNombre = Literal[
    "ACCESO", "PARTICIPACION", "APRENDIZAJE", "BIENESTAR", "AUTONOMIA", "PERMANENCIA", "PROGRESION", "GRADUACION",
    "TRANSICION_PROFESIONAL",
]


class DimensionesIn(_Estricto):
    ACCESO: DimAcceso | None = None
    PARTICIPACION: DimParticipacion | None = None
    APRENDIZAJE: DimAprendizaje | None = None
    BIENESTAR: DimBienestar | None = None
    AUTONOMIA: DimAutonomia | None = None
    PERMANENCIA: DimPermanencia | None = None
    PROGRESION: DimProgresion | None = None
    GRADUACION: DimGraduacion | None = None
    TRANSICION_PROFESIONAL: DimTransicionProfesional | None = None


# --------------------------------------------------------------------------- trayectoria por semestre
class TrayectoriaCrear(_Estricto):
    semestre_academico: str = Field(pattern=SEMESTRE_PATTERN, examples=["2026-II"])
    fecha_inicio_semestre: date | None = None  # si falta se toma del calendario academico
    fecha_fin_semestre: date | None = None
    asignaturas_inscritas: int | None = Field(default=None, ge=0, le=40)
    asignaturas_completadas: int | None = Field(default=None, ge=0, le=40)
    creditos_aprobados: int | None = Field(default=None, ge=0, le=60)
    promedio_academico: float | None = Field(default=None, ge=0, le=5)
    dimensiones: DimensionesIn | None = None

    @model_validator(mode="after")
    def _coherencia(self):
        if self.asignaturas_inscritas is not None and self.asignaturas_completadas is not None \
                and self.asignaturas_completadas > self.asignaturas_inscritas:
            raise ValueError("las asignaturas completadas no pueden superar las inscritas")
        return self


class TrayectoriaPatch(_Estricto):
    fecha_inicio_semestre: date | None = None
    fecha_fin_semestre: date | None = None
    asignaturas_inscritas: int | None = Field(default=None, ge=0, le=40)
    asignaturas_completadas: int | None = Field(default=None, ge=0, le=40)
    creditos_aprobados: int | None = Field(default=None, ge=0, le=60)
    promedio_academico: float | None = Field(default=None, ge=0, le=5)
    dimensiones: DimensionesIn | None = None


class HitoCrear(_Estricto):
    tipo_hito: TipoHito
    fecha_hito: date
    descripcion: str | None = Field(default=None, max_length=2000)
    semestre_academico: str | None = Field(default=None, pattern=SEMESTRE_PATTERN)  # enlaza con la trayectoria


class HitoPatch(_Estricto):
    tipo_hito: TipoHito | None = None
    fecha_hito: date | None = None
    descripcion: str | None = Field(default=None, max_length=2000)


class HitoOut(BaseModel):
    id: int
    estudiante_id: int
    trayectoria_id: int | None
    semestre_academico: str | None
    tipo_hito: str
    fecha_hito: date
    descripcion: str | None
    registrado_por_id: int | None


class TrayectoriaOut(BaseModel):
    id: int
    estudiante_id: int
    semestre_academico: str
    fecha_inicio_semestre: date
    fecha_fin_semestre: date | None
    asignaturas_inscritas: int | None
    asignaturas_completadas: int | None
    creditos_aprobados: int | None
    promedio_academico: float | None
    dimensiones: dict[str, dict[str, Any] | None]  # las 9 claves siempre presentes; null = sin diligenciar


class TrayectoriaListaOut(BaseModel):
    estudiante_id: int
    resumen: dict[str, Any]
    trayectorias: list[TrayectoriaOut]
    hitos: list[HitoOut]


# --------------------------------------------------------------------------- F10
class ItemDecisionIn(_Estricto):
    elemento: Literal["AJUSTE", "ESTRATEGIA"]
    elemento_id: int = Field(ge=1)
    tipo_decision: Literal["MANTENER", "MODIFICAR", "RETIRAR"]
    descripcion_cambio: str | None = Field(default=None, max_length=4000)
    justificacion: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _modificar_requiere_descripcion(self):
        if self.tipo_decision == "MODIFICAR" and not (self.descripcion_cambio or "").strip():
            raise ValueError("para modificar un ajuste o estrategia describa cómo queda en el siguiente semestre")
        return self


class ActualizacionPlanPatch(_Estricto):
    items: list[ItemDecisionIn] | None = None
    nuevos_propuestos: list[str] | None = Field(default=None, max_length=30)
    observaciones: str | None = Field(default=None, max_length=4000)


class NecesidadIn(_Estricto):
    tipo: Literal["PRACTICAS", "PASANTIAS", "TRABAJO_GRADO", "OTRA"]
    semestre_estimado: str | None = Field(default=None, pattern=SEMESTRE_PATTERN)
    descripcion: str | None = Field(default=None, max_length=2000)
    apoyos_previstos: str | None = Field(default=None, max_length=2000)


class F10TrayectoriaPatch(_Estricto):
    """Componente 2 del F10: datos del semestre + 9 dimensiones + proyeccion y necesidades anticipadas."""

    trayectoria: TrayectoriaPatch | None = None
    necesidades_anticipadas: list[NecesidadIn] | None = Field(default=None, max_length=20)
    proyeccion: dict[str, Any] | None = None  # ajustes manuales de la proyeccion (se fusionan con la calculada)


class F10Generar(_Estricto):
    semestre_origen: str | None = Field(default=None, pattern=SEMESTRE_PATTERN)
    semestre_destino: str | None = Field(default=None, pattern=SEMESTRE_PATTERN)


class F10Aprobar(_Estricto):
    comentario: str | None = Field(default=None, max_length=2000)


class AprobacionOut(BaseModel):
    usuario_id: int | None
    nombre: str | None
    aprobado_at: datetime | None


class F10ResumenOut(BaseModel):
    id: int
    estudiante_id: int
    semestre_origen: str
    semestre_destino: str
    estado: str
    plan_id: int | None
    evaluacion_id: int | None
    trayectoria_id: int | None
    plan_siguiente_id: int | None
    generado_at: datetime
    aprobacion_bienestar: AprobacionOut
    aprobacion_estudiante: AprobacionOut
    aprobado_at: datetime | None


class F10Out(F10ResumenOut):
    comentario_estudiante: str | None
    actualizacion_plan: dict[str, Any]
    trayectoria: dict[str, Any] | None
    necesidades_anticipadas: list[dict[str, Any]]
    proyeccion: dict[str, Any] | None
    notas: list[dict[str, Any]]
    advertencias: list[str] = []


# --------------------------------------------------------------------------- notas de continuidad (RF-35)
class NotaCrear(_Estricto):
    contenido: str = Field(min_length=3, max_length=8000)
    destinatario: Literal["TODOS", "DOCENTE", "COORDINADOR", "BIENESTAR"] = "TODOS"


class NotaPatch(_Estricto):
    contenido: str | None = Field(default=None, min_length=3, max_length=8000)
    destinatario: Literal["TODOS", "DOCENTE", "COORDINADOR", "BIENESTAR"] | None = None


class NotaRechazar(_Estricto):
    motivo: str = Field(min_length=3, max_length=2000)


class NotaOut(BaseModel):
    id: int
    estudiante_id: int
    plan_id: int | None
    semestre_origen: str
    semestre_destino: str | None
    destinatario: str
    estado: str
    contenido: str
    elaborada_por_id: int
    elaborada_por_rol: str | None
    aprobada_por_estudiante: bool
    aprobada_at: datetime | None
    motivo_rechazo: str | None
    created_at: datetime
    updated_at: datetime
    advertencia: str | None = None
