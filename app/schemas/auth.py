"""Schemas de autenticación y del usuario actual (`/auth/me`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import EspaciadoUI, FuenteUI
from app.schemas.common import ORMModel


class PreferenciasUI(ORMModel):
    modo_calma: bool = False
    tamano_texto: Literal[100, 115, 130] = 100
    espaciado: str = EspaciadoUI.NORMAL
    sin_movimiento: bool = False
    alto_contraste: bool = False
    fuente: str = FuenteUI.PREDETERMINADA


_ESPACIADO_ALIAS = {
    "NORMAL": "NORMAL", "ESTANDAR": "NORMAL", "DEFAULT": "NORMAL", "0": "NORMAL",
    "AMPLIO": "AMPLIO", "WIDE": "AMPLIO", "RELAJADO": "AMPLIO", "1": "AMPLIO",
    "MUY_AMPLIO": "MUY_AMPLIO", "MUYAMPLIO": "MUY_AMPLIO", "WIDER": "MUY_AMPLIO", "EXTRA": "MUY_AMPLIO", "2": "MUY_AMPLIO",
}
_FUENTE_ALIAS = {
    "PREDETERMINADA": "PREDETERMINADA", "DEFAULT": "PREDETERMINADA", "ATKINSON": "PREDETERMINADA",
    "LEXEND": "PREDETERMINADA", "ESTANDAR": "PREDETERMINADA",
    "DISLEXIA": "DISLEXIA", "DYSLEXIA": "DISLEXIA", "OPENDYSLEXIC": "DISLEXIA", "DYSLEXIC": "DISLEXIA",
    "SISTEMA": "SISTEMA", "SYSTEM": "SISTEMA",
}


class PreferenciasUIUpdate(BaseModel):
    """PATCH parcial. Acepta valores en mayúsculas o minúsculas (y alias comunes) y los normaliza."""

    modo_calma: bool | None = None
    tamano_texto: Literal[100, 115, 130] | None = None
    espaciado: str | None = None
    sin_movimiento: bool | None = None
    alto_contraste: bool | None = None
    fuente: str | None = None

    @field_validator("espaciado")
    @classmethod
    def _espaciado(cls, v):
        if v is None:
            return v
        key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
        if key not in _ESPACIADO_ALIAS:
            raise ValueError("debe ser NORMAL, AMPLIO o MUY_AMPLIO")
        return _ESPACIADO_ALIAS[key]

    @field_validator("fuente")
    @classmethod
    def _fuente(cls, v):
        if v is None:
            return v
        key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
        if key not in _FUENTE_ALIAS:
            raise ValueError("debe ser PREDETERMINADA, DISLEXIA o SISTEMA")
        return _FUENTE_ALIAS[key]


class Me(ORMModel):
    id: int
    email: str
    nombre_completo: str
    rol: str
    estado: str
    consentimiento_firmado: bool
    programa_id: int | None = None
    preferencias_ui: PreferenciasUI


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class LoginResponse(TokenResponse):
    user: Me


class ActivateRequest(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    password: str = Field(min_length=1, max_length=200)


class ActivateResponse(BaseModel):
    detail: str
    email: str
    estado: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str
