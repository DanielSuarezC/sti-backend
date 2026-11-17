"""Schemas de administración: AQ-10, jobs y cola de correo (slice A)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Aq10Item(BaseModel):
    numero: int = Field(ge=1, le=10)
    texto: str = Field(min_length=1, max_length=500)
    puntua_si: Literal["ACUERDO", "DESACUERDO"]


class Aq10Opcion(BaseModel):
    valor: int = Field(ge=1, le=4)
    etiqueta: str = Field(min_length=1, max_length=100)
    direccion: Literal["ACUERDO", "DESACUERDO"]


class Aq10Update(BaseModel):
    items: list[Aq10Item]
    opciones: list[Aq10Opcion]
    instrucciones: str | None = Field(None, max_length=2000)
    nombre: str | None = Field(None, max_length=255)
    idioma: str | None = Field(None, max_length=20)
    fuente: str | None = Field(None, max_length=500)
    revision_linguistica_pendiente: bool | None = None
    punto_corte: int | None = None


class PuntoCorteBody(BaseModel):
    punto_corte: int


class OutboxRetry(BaseModel):
    ids: list[int] | None = None
    limite: int = Field(100, ge=1, le=500)
