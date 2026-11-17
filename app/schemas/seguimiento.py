"""Schemas de F8 (seguimiento por cortes, semaforo, percepcion, evidencias, barreras emergentes) y de inasistencia.

# OWNER: slice C2
Todos los cuerpos de entrada prohiben campos desconocidos (`extra="forbid"`): asi, por ejemplo, el endpoint de Bienestar
rechaza con 422 cualquier intento de escribir la percepcion del estudiante (HU-21).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    DimensionResultado,
    Escenario,
    Frecuencia,
    PercepcionEstudiante,
    Semaforo,
    Severidad,
    TipoAjuste,
    TipoBarrera,
    TipoEvidenciaEfectividad,
    TipoRegistroSeguimiento,
)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ----------------------------------------------------------------------------- corte
class SeguimientoAbrir(_In):
    """`POST /planes/{id}/seguimiento/{corte}`: todos los campos son opcionales (se pueden completar luego con PATCH)."""

    fecha_seguimiento: date | None = None
    participantes_ids: list[int] | None = None
    descripcion_situacion_actual: str | None = Field(default=None, max_length=5000)
    funcionamiento_apoyos: str | None = Field(default=None, max_length=5000)
    dificultades_emergentes: str | None = Field(default=None, max_length=5000)
    ajustes_recomendados: str | None = Field(default=None, max_length=5000)
    observaciones_generales: str | None = Field(default=None, max_length=5000)


class SeguimientoPatch(SeguimientoAbrir):
    pass


class RegistroAjusteIn(_In):
    """`PUT .../ajustes/{ajuste_id}` (solo Bienestar). NO incluye percepcion del estudiante (solo ella la escribe)."""

    semaforo: Semaforo | None = None
    implementado: bool | None = None
    frecuencia_implementacion: str | None = Field(default=None, max_length=255)
    resultado_observado: str | None = Field(default=None, max_length=5000)

    @field_validator("resultado_observado", "frecuencia_implementacion")
    @classmethod
    def _vacio_a_none(cls, v):
        return v or None


class PercepcionIn(_In):
    """`PUT .../ajustes/{ajuste_id}/percepcion` (solo el estudiante)."""

    percepcion: PercepcionEstudiante
    comentario: str | None = Field(default=None, max_length=3000)


class ConcertacionResolver(_In):
    acuerdo: str = Field(min_length=5, max_length=3000, description="Lo que acordaron Bienestar y el estudiante.")


class RedisenoIn(_In):
    """Registro del rediseno de un ajuste en ROJO (desbloquea el avance al siguiente corte)."""

    decision: Literal["MODIFICAR", "REEMPLAZAR", "RETIRAR"]
    descripcion: str = Field(min_length=10, max_length=3000, description="Que cambia y por que.")
    concertado_con_estudiante: bool = False
    nueva_version_plan: int | None = Field(default=None, ge=1, description="Version del plan donde queda el cambio (si aplica).")


class RegistroSeguimientoIn(_In):
    tipo_registro: TipoRegistroSeguimiento
    descripcion_metodologia: str | None = Field(default=None, max_length=5000)
    fuentes_informacion: str | None = Field(default=None, max_length=500)


class ResultadoIndicadorIn(_In):
    dimension_resultado: DimensionResultado
    indicador_especifico: str = Field(min_length=3, max_length=1000)
    valor_logrado: str | None = Field(default=None, max_length=1000)
    meta_establecida: str | None = Field(default=None, max_length=1000)
    porcentaje_cumplimiento: int | None = Field(default=None, ge=0, le=100)
    interpretacion: str | None = Field(default=None, max_length=2000)


class EvidenciaIn(_In):
    tipo_evidencia: TipoEvidenciaEfectividad
    descripcion_evidencia: str = Field(min_length=3, max_length=5000)
    fuente_evidencia: str | None = Field(default=None, max_length=255)
    dato_cuantitativo: Decimal | None = Field(default=None, ge=-99999999, le=99999999)
    periodo_medicion: str | None = Field(default=None, max_length=100)
    resultados: list[ResultadoIndicadorIn] = Field(default_factory=list, max_length=20)


class PropuestaAjusteIn(_In):
    nombre_ajuste: str = Field(min_length=3, max_length=200)
    descripcion_ajuste: str = Field(min_length=3, max_length=3000)
    justificacion: str = Field(min_length=3, max_length=3000)
    tipo_ajuste: TipoAjuste


class BarreraEmergenteIn(_In):
    """Barrera no prevista en el F4 original, detectada en el F8 (v7 M6)."""

    tipo_barrera: TipoBarrera
    escenario: Escenario | None = None
    descripcion_barrera: str = Field(min_length=5, max_length=3000)
    severidad: Severidad = Severidad.MODERADA
    frecuencia: Frecuencia = Frecuencia.FRECUENTE
    ajuste_id: int | None = Field(default=None, description="Ajuste del plan al que afecta (opcional).")
    propuesta_ajuste: PropuestaAjusteIn | None = None
    propuesta_respuesta_institucional: str | None = Field(
        default=None, max_length=3000, description="Obligatoria si la barrera es SOCIAL (RF-19)."
    )


# ----------------------------------------------------------------------------- inasistencia
class InasistenciaIn(_In):
    porcentaje_inasistencia: Decimal = Field(ge=0, le=100, decimal_places=2)
    semestre_academico: str | None = Field(default=None, max_length=20, description="Por defecto, el del calendario activo.")
    asignatura_id: int | None = None
    fecha_registro: date | None = None
    observaciones: str | None = Field(default=None, max_length=2000)


class InasistenciaSigaaIn(_In):
    semestre_academico: str | None = Field(default=None, max_length=20)
