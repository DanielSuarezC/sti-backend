"""Schemas de entrada de la negociación (RF-25)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.planes import AjusteUpdate


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContrapropuestaIn(_In):
    propuesta: str = Field(min_length=5, max_length=2000, description="Contrapropuesta de Bienestar a la objeción")
    cambios_ajuste: AjusteUpdate | None = Field(None, description="Cambios que se aplican al ajuste en el mismo acto")


class ResponderNegociacionIn(_In):
    acepta: bool
    comentario: str | None = Field(None, max_length=2000, description="Obligatorio (>= 5 caracteres) si no acepta: es la nueva objeción")


class ResultadoCierre(StrEnum):
    ACORDADO = "ACORDADO"
    RETIRAR_AJUSTE = "RETIRAR_AJUSTE"
    MANTENER_POR_COMITE = "MANTENER_POR_COMITE"


class CerrarNegociacionIn(_In):
    resultado: ResultadoCierre
    resolucion: str = Field(min_length=5, max_length=2000)
