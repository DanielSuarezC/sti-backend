"""Schemas de F1 (caracterización) y F2 (perfil de fortalezas). PATCH por sección, idempotente (upsert)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    IntensidadInteres,
    NivelAutonomia,
    NivelBMA,
    NivelBMAC,
    NivelConsolidacion,
    TipoEstrategiaAprendizaje,
    TipoSensorial,
)
from app.models.slice_b import TipoMeta


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ F1
class HistoriaAcademicaIn(_In):
    trayectoria_escolar: str | None = None
    apoyos_previos: str | None = None
    experiencias_exitosas: str | None = None
    dificultades_previas: str | None = None
    otras_observaciones: str | None = None


class ComunicacionItem(_In):
    id: int | None = None
    tipo_comunicacion: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(min_length=1)
    fortalezas_comunicacion: str | None = None
    dificultades_comunicacion: str | None = None
    estrategias_favorables: str | None = None


class SensorialItem(_In):
    id: int | None = None
    tipo_sensorial: TipoSensorial
    hipersensibilidad: bool | None = None
    hiposensibilidad: bool | None = None
    descripcion_experiencia: str | None = None
    impacto_academico: str | None = None
    estrategias_autoregulacion: str | None = None


class AutonomiaItem(_In):
    id: int | None = None
    contexto_autonomia: str = Field(min_length=1, max_length=100)
    nivel_autonomia: NivelAutonomia
    actividades_autonomas: str | None = None
    actividades_con_apoyo: str | None = None
    actividades_supervisadas: str | None = None


class PreferenciaItem(_In):
    id: int | None = None
    tipo_preferencia: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(min_length=1)
    prioridad: NivelBMAC = NivelBMAC.MEDIA
    razon_preferencia: str | None = None


class ResumenIn(_In):
    resumen_ejecutivo: str | None = None


class AutodescripcionIn(_In):
    autodescripcion_estudiante: str | None = None


class _ListaIn(_In):
    quitar: list[int | str] = Field(default_factory=list, description="Claves (o ids) de elementos a archivar")


class ComunicacionIn(_ListaIn):
    items: list[ComunicacionItem] = Field(default_factory=list)


class SensorialIn(_ListaIn):
    items: list[SensorialItem] = Field(default_factory=list)


class AutonomiaIn(_ListaIn):
    items: list[AutonomiaItem] = Field(default_factory=list)


class PreferenciasIn(_ListaIn):
    items: list[PreferenciaItem] = Field(default_factory=list)


# ------------------------------------------------------------------ F2
class FortalezaItem(_In):
    id: int | None = None
    nombre_fortaleza: str = Field(min_length=1, max_length=200)
    descripcion_detallada: str = Field(min_length=1)
    areas_aplicacion: str | None = Field(default=None, max_length=500)
    nivel_consolidacion: NivelConsolidacion = NivelConsolidacion.CONSOLIDADA


class InteresItem(_In):
    id: int | None = None
    nombre_interes: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(min_length=1)
    intensidad: IntensidadInteres = IntensidadInteres.MODERADO
    aplicacion_academica: str | None = None
    aplicacion_laboral: str | None = None


class EstrategiaItem(_In):
    id: int | None = None
    nombre_estrategia: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(min_length=1)
    tipo_estrategia: TipoEstrategiaAprendizaje
    efectividad_reportada: NivelBMA = NivelBMA.ALTA
    contextos_aplicacion: str | None = None


class MetaItem(_In):
    id: int | None = None
    tipo: TipoMeta = TipoMeta.ACADEMICA
    descripcion: str = Field(min_length=1)
    plazo: str | None = Field(default=None, max_length=50)
    prioridad: NivelBMA = NivelBMA.MEDIA


class FortalezasIn(_ListaIn):
    items: list[FortalezaItem] = Field(default_factory=list)


class InteresesIn(_ListaIn):
    items: list[InteresItem] = Field(default_factory=list)


class EstrategiasIn(_ListaIn):
    items: list[EstrategiaItem] = Field(default_factory=list)


class MetasIn(_ListaIn):
    items: list[MetaItem] = Field(default_factory=list)


class NarrativasIn(_In):
    narrativa_fortalezas: str | None = None
    narrativa_intereses: str | None = None
    narrativa_estrategias: str | None = None


class ComentarioIn(_In):
    formato: Literal["F1", "F2"]
    seccion: str = Field(min_length=1, max_length=50)
    texto: str = Field(min_length=1, max_length=4000)


F1_SECCIONES_IN = {
    "historia_academica": HistoriaAcademicaIn, "comunicacion": ComunicacionIn, "sensorial": SensorialIn,
    "autonomia": AutonomiaIn, "preferencias": PreferenciasIn, "resumen": ResumenIn, "autodescripcion": AutodescripcionIn,
}
F2_SECCIONES_IN = {
    "fortalezas": FortalezasIn, "intereses": InteresesIn, "estrategias": EstrategiasIn, "metas": MetasIn,
    "narrativas": NarrativasIn,
}
