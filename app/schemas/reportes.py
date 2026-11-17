"""Schemas de reportes (slice A)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReferenciaBody(BaseModel):
    permanencia_pct: float | None = Field(None, ge=0, le=100)
    avance_promedio_pct: float | None = Field(None, ge=0, le=100)
    graduacion_pct: float | None = Field(None, ge=0, le=100)
    promedio_academico: float | None = Field(None, ge=0, le=5)
    fuente: str | None = Field(None, max_length=300)
