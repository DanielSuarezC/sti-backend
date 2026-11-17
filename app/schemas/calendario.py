"""Schemas de calendario académico y parámetros (slice A)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

SEMESTRE = r"^\d{4}-(I|II)$"


class CalendarioCreate(BaseModel):
    semestre_academico: str = Field(pattern=SEMESTRE)
    programa_id: int | None = None
    fecha_inicio: date
    fecha_fin: date
    fecha_c1: date
    fecha_c2: date
    fecha_c3: date
    fecha_inicio_practicas: date | None = None
    umbral_inasistencia: float | None = Field(None, ge=1, le=100)
    activo: bool = False


class CalendarioUpdate(BaseModel):
    semestre_academico: str | None = Field(None, pattern=SEMESTRE)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    fecha_c1: date | None = None
    fecha_c2: date | None = None
    fecha_c3: date | None = None
    fecha_inicio_practicas: date | None = None
    umbral_inasistencia: float | None = Field(None, ge=1, le=100)


class ParametroBody(BaseModel):
    valor: Any
