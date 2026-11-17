"""Schemas de sugerencias DUA."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenerarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barrera_ids: list[int] | None = Field(default=None, description="Solo estas barreras; por defecto, todas las vigentes")
    max_por_barrera: int = Field(default=3, ge=1, le=10)


class AceptarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nota: str | None = Field(default=None, max_length=1000)


class ModificarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto_modificado: str = Field(min_length=5, max_length=4000)
    motivo: str | None = Field(default=None, max_length=1000)


class RechazarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motivo: str = Field(min_length=5, max_length=1000)
