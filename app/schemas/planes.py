"""Schemas de entrada del Plan MAAR-TEA (slice C1). Las respuestas son diccionarios documentados en docs/api/slice_c1.md."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    DimensionDua,
    DisponibilidadRecurso,
    Escenario,
    EspecificidadAjuste,
    EstadoApoyo,
    IntensidadApoyo,
    TipoAjuste,
    TipoRecurso,
)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanCreate(_In):
    semestre_academico: str | None = Field(None, max_length=20, description="Por defecto, el semestre del calendario activo")
    resumen_ejecutivo: str | None = None
    justificacion_apoyos: str | None = None
    incluir_sugerencias: bool = True


class PlanUpdate(_In):
    resumen_ejecutivo: str | None = None
    justificacion_apoyos: str | None = None
    vigencia_fin: date | None = None
    participacion_familia: bool | None = None
    profesionales_responsables_ids: list[int] | None = None


class MotivoIn(_In):
    motivo: str = Field(min_length=3, max_length=500)


class DetalleAjusteIn(_In):
    tipo: str = Field(description="Valor del enum de la categoría (p. ej. REDUCCION_ESTIMULOS para AMBIENTE)")
    descripcion: str | None = None
    soporte_tecnico_requerido: bool = False


class AjusteCreate(_In):
    tipo_ajuste: TipoAjuste
    detalle: DetalleAjusteIn
    nombre_ajuste: str = Field(min_length=3, max_length=200)
    descripcion_ajuste: str = Field(min_length=5)
    justificacion: str | None = None
    barrera_asociada_id: int = Field(description="Obligatoria: la barrera (F4) que resuelve el ajuste")
    fortaleza_apoyo_id: int | None = None
    responsable_id: int | None = None
    asignatura_id: int | None = None
    asignatura_si_aplica: str | None = Field(None, max_length=200)
    actividad_si_aplica: str | None = Field(None, max_length=500)
    especificidad: EspecificidadAjuste | None = None
    recurso: str | None = Field(None, max_length=500)
    frecuencia: str | None = Field(None, max_length=200)
    indicador_efectividad: str | None = None
    fecha_inicio: date | None = None
    fecha_fin_prevista: date | None = None
    permanencia_indefinida: bool | None = None


class AjusteUpdate(_In):
    tipo_ajuste: TipoAjuste | None = None
    detalle: DetalleAjusteIn | None = None
    nombre_ajuste: str | None = Field(None, min_length=3, max_length=200)
    descripcion_ajuste: str | None = Field(None, min_length=5)
    justificacion: str | None = None
    barrera_asociada_id: int | None = None
    fortaleza_apoyo_id: int | None = None
    responsable_id: int | None = None
    asignatura_id: int | None = None
    asignatura_si_aplica: str | None = Field(None, max_length=200)
    actividad_si_aplica: str | None = Field(None, max_length=500)
    especificidad: EspecificidadAjuste | None = None
    recurso: str | None = Field(None, max_length=500)
    frecuencia: str | None = Field(None, max_length=200)
    indicador_efectividad: str | None = None
    fecha_inicio: date | None = None
    fecha_fin_prevista: date | None = None
    permanencia_indefinida: bool | None = None


class EstrategiaCreate(_In):
    nombre_estrategia: str | None = Field(None, max_length=200)
    descripcion: str | None = None
    dimension_dua: DimensionDua | None = None
    estrategia_catalogo_id: int | None = None
    barrera_id: int | None = None
    fortaleza_id: int | None = None
    responsable_implementacion_id: int | None = None
    asignatura_id: int | None = None
    escenario: Escenario | None = None
    alcance: str | None = Field(None, max_length=255)
    fecha_inicio_implementacion: date | None = None


class EstrategiaUpdate(_In):
    nombre_estrategia: str | None = Field(None, max_length=200)
    descripcion: str | None = None
    dimension_dua: DimensionDua | None = None
    barrera_id: int | None = None
    fortaleza_id: int | None = None
    responsable_implementacion_id: int | None = None
    asignatura_id: int | None = None
    escenario: Escenario | None = None
    alcance: str | None = Field(None, max_length=255)
    fecha_inicio_implementacion: date | None = None


class RespuestaEstudianteTipo(StrEnum):
    ACEPTADO = "ACEPTADO"
    MODIFICACION_PROPUESTA = "MODIFICACION_PROPUESTA"
    OBJETADO = "OBJETADO"


class RespuestaEstudianteIn(_In):
    respuesta: RespuestaEstudianteTipo
    comentario: str | None = Field(None, max_length=2000, description="Obligatorio (>= 5 caracteres) si propone modificación u objeta")


class AceptacionDocenteIn(_In):
    acepta: bool
    comentario: str | None = Field(None, max_length=2000, description="Obligatorio si no acepta")


class ValidarIn(_In):
    comentario: str | None = Field(None, max_length=2000)


class DevolverIn(_In):
    comentarios: str = Field(min_length=5, max_length=2000)


class FirmarIn(_In):
    confirmo: bool = Field(description="Debe ser true: confirma que leyó el plan y firma con su cuenta")


class RecursoIn(_In):
    tipo_recurso: TipoRecurso | None = None
    descripcion_recurso: str | None = None
    cantidad: int | None = Field(None, ge=0)
    unidad_medida: str | None = Field(None, max_length=50)
    disponibilidad: DisponibilidadRecurso | None = None


class ApoyoUpdate(_In):
    fecha_inicio: date | None = None
    fecha_fin_prevista: date | None = None
    intensidad: IntensidadApoyo | None = None
    estado: EstadoApoyo | None = None
    objetivo: str | None = None
    continuidad_indefinida: bool | None = None
    frecuencia: str | None = Field(None, max_length=200)
    responsable_principal_id: int | None = None
    responsable_secundario_id: int | None = None
    recurso: RecursoIn | None = None


class MatrizGenerarIn(_In):
    sobrescribir: bool = Field(False, description="true: restablece fechas, responsables y recursos editados a mano")
