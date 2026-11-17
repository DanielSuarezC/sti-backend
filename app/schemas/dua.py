"""Schemas del catálogo DUA (slice A)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Escenario, PrincipioDua, TipoBarrera


class EstrategiaCreate(BaseModel):
    codigo: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=3, max_length=255)
    descripcion_pedagogica: str = Field(min_length=10)
    principio: PrincipioDua
    pauta: int = Field(ge=1, le=9)
    pauta_nombre: str | None = Field(None, max_length=200)
    punto_verificacion: str | None = Field(None, pattern=r"^[1-9]\.[1-9]$")
    escenarios: list[Escenario] = []
    tipos_barrera: list[TipoBarrera] = []
    perfil_estudiante: str | None = None
    fuente: str | None = Field(None, max_length=500)
    activo: bool = True


class EstrategiaUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=3, max_length=255)
    descripcion_pedagogica: str | None = Field(None, min_length=10)
    principio: PrincipioDua | None = None
    pauta: int | None = Field(None, ge=1, le=9)
    pauta_nombre: str | None = Field(None, max_length=200)
    punto_verificacion: str | None = Field(None, pattern=r"^[1-9]\.[1-9]$")
    escenarios: list[Escenario] | None = None
    tipos_barrera: list[TipoBarrera] | None = None
    perfil_estudiante: str | None = None
    fuente: str | None = Field(None, max_length=500)
    activo: bool | None = None
