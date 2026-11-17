"""Schemas de F0 (consentimiento) y ARCO."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.slice_b import EstadoArco, TipoArco


class FirmarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_texto: str = Field(description="Versión del texto que se mostró (de GET /consentimiento/texto)")
    texto_hash: str = Field(description="SHA-256 del texto mostrado (de GET /consentimiento/texto)")
    nombre_firmante: str = Field(min_length=3, max_length=255, description="Nombre tecleado por el estudiante")
    acepta_tratamiento_general: bool
    acepta_datos_sensibles_salud: bool
    acepta_compartir_ajustes_docentes: bool = False
    estudiante_id: int | None = Field(
        default=None, description="Solo para BIENESTAR (firma asistida): estudiante que firma en su acompañamiento"
    )


class RevocarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmar: bool = Field(description="Debe ser true: confirma que entiende que la cuenta se inactiva")
    motivo: str | None = Field(default=None, max_length=1000, description="Opcional: no está obligado a explicar")


class ArcoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: TipoArco
    descripcion: str = Field(min_length=10, max_length=4000)


class ArcoGestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: EstadoArco = Field(description="EN_TRAMITE | RESUELTA | RECHAZADA")
    respuesta: str | None = Field(default=None, max_length=8000)


class ArcoProrrogaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: str = Field(min_length=10, max_length=500)
