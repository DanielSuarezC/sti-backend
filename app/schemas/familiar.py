"""Schemas del Familiar Autorizado (D9, HU-22/28, Ley 1996/2019)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AlcanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: bool = False
    seguimiento: bool = False
    caracterizacion: bool = False  # F1-F2
    notificaciones: bool = False  # avisos de seguimiento


class AlcanceParcial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: bool | None = None
    seguimiento: bool | None = None
    caracterizacion: bool | None = None
    notificaciones: bool | None = None


class FamiliarCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=2, max_length=255)
    email: EmailStr
    parentesco: str | None = Field(default=None, max_length=100)
    alcance: AlcanceIn
    vigencia_hasta: date | None = None


class FamiliarPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = Field(default=None, min_length=2, max_length=255)
    parentesco: str | None = Field(default=None, max_length=100)
    alcance: AlcanceParcial | None = None
    vigencia_hasta: date | None = None  # enviar null explicito = sin vencimiento


class AutorizacionOut(BaseModel):
    id: int
    familiar_nombre: str
    familiar_email: str
    parentesco: str | None
    alcance: dict[str, bool]
    estado: str  # PENDIENTE | VIGENTE | REVOCADA | EXPIRADA
    cuenta_activada: bool
    otorgada_at: datetime
    vigencia_hasta: datetime | None
    revocada_at: datetime | None
    motivo_revocacion: str | None
    codigo_vinculacion: str | None = None  # solo mientras está PENDIENTE: el familiar lo usa al registrarse


class EstudianteAutorizadoOut(BaseModel):
    estudiante_id: int
    nombre: str
    parentesco: str | None
    alcance: dict[str, bool]
    vigencia_hasta: datetime | None
    otorgada_at: datetime


class PlanFamiliarOut(BaseModel):
    estudiante: dict[str, Any]
    plan: dict[str, Any]


class SeguimientoFamiliarOut(BaseModel):
    estudiante: dict[str, Any]
    semestre: str
    cortes: list[dict[str, Any]]


class CaracterizacionFamiliarOut(BaseModel):
    estudiante: dict[str, Any]
    caracterizacion: dict[str, Any] | None
    fortalezas: dict[str, Any] | None
