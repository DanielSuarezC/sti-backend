"""Schemas de solicitudes de ingreso Vía 2 (slice A)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SolicitudPublica(BaseModel):
    codigo_estudiantil: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9\-_.]+$")
    email_institucional: EmailStr
    nombre_completo: str = Field(min_length=3, max_length=255)
    telefono: str | None = Field(None, max_length=20)
    programa_id: int | None = None
    acepta_aviso_privacidad: bool
    sitio_web: str | None = Field(None, max_length=200)  # honeypot: debe ir vacío


class AprobarBody(BaseModel):
    programa_id: int | None = None


class RechazarBody(BaseModel):
    motivo: str = Field(min_length=5, max_length=500)
