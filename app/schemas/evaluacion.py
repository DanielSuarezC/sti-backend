"""Schemas del F9 (evaluacion de efectividad).

# OWNER: slice C2
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DimensionResultado, NivelBMA, TipoDecision


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DecisionIn(_In):
    """Decision del F9 por ajuste. `justificacion` es obligatoria (RF-33). `ajuste_id` nulo = CREAR_NUEVO."""

    ajuste_id: int | None = None
    tipo_decision: TipoDecision
    justificacion: str = Field(min_length=5, max_length=3000)
    lecciones_aprendidas: str | None = Field(default=None, max_length=3000)
    descripcion_decision: str | None = Field(default=None, max_length=3000, description="Obligatoria para CREAR_NUEVO.")
    fecha_implementacion_decision: date | None = None


class ValoracionDimension(_In):
    nivel: NivelBMA
    comentario: str | None = Field(default=None, max_length=2000)


class EvaluacionPatch(_In):
    efectividad_general: NivelBMA | None = None
    nuevas_barreras_identificadas: str | None = Field(default=None, max_length=5000)
    fortalezas_emergentes: str | None = Field(default=None, max_length=5000)
    cambios_contexto: str | None = Field(default=None, max_length=5000)
    recomendaciones: str | None = Field(default=None, max_length=5000)
    lecciones_aprendidas: str | None = Field(default=None, max_length=5000)
    valoracion_dimensiones: dict[DimensionResultado, ValoracionDimension] | None = None
    decisiones: list[DecisionIn] | None = Field(default=None, max_length=100)
