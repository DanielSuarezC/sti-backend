"""Schemas del AQ-10."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Aq10In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respuestas: dict[int, int] = Field(
        description='Mapa ítem -> opción elegida: {"1": 1, ..., "10": 4}. Valores según GET /aq10/formulario (1..4).'
    )
