"""Schemas del panel del Docente (HU-23/24, D10). Los modelos de salida son una lista BLANCA de campos: aunque el
servicio devolviera algo de mas, FastAPI lo descarta (nunca hay AQ-10, F1, F2, barreras, diagnostico ni notas)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImplementacionAjusteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    implementado: bool
    fecha: date
    nota: str | None = Field(default=None, max_length=2000)


class ImplementacionEstrategiaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["INICIADA", "IMPLEMENTADA"]
    fecha: date | None = None  # por defecto, hoy
    nota: str | None = Field(default=None, max_length=2000)


class AsignaturaOut(BaseModel):
    id: int
    codigo: str
    nombre: str


class UltimaImplementacionOut(BaseModel):
    id: int
    fecha: date
    implementado: bool
    nota: str | None


class AjusteDocenteOut(BaseModel):
    id: int
    nombre_ajuste: str
    descripcion: str
    tipo_ajuste: str
    categorias: list[str]
    frecuencia: str | None
    indicador_efectividad: str | None
    actividad_si_aplica: str | None
    fecha_inicio: date
    fecha_fin_prevista: date | None
    permanencia_indefinida: bool
    estado: str
    semaforo_actual: str | None
    semestre: str
    plan_estado: str
    es_responsable: bool
    ultima_implementacion: UltimaImplementacionOut | None


class EstrategiaDocenteOut(BaseModel):
    id: int
    nombre_estrategia: str
    descripcion: str
    dimension_dua: str
    alcance: str | None
    escenario: str | None
    estado_implementacion: str
    implementada: bool
    nota_implementacion: str | None
    implementada_at: datetime | None
    semestre: str
    plan_estado: str


class EstudianteAliasOut(BaseModel):
    alias: str
    iniciales: str | None
    ajustes: list[AjusteDocenteOut]
    estrategias_dua: list[EstrategiaDocenteOut]


class GrupoAsignaturaOut(BaseModel):
    asignatura: AsignaturaOut | None
    estudiantes: list[EstudianteAliasOut]


class MisAjustesOut(BaseModel):
    docente_ve_nombre: bool
    total_ajustes: int
    total_estrategias: int
    asignaturas: list[GrupoAsignaturaOut]


class CorteSemaforoOut(BaseModel):
    corte: str
    semaforo: str | None
    implementado: bool | None


class AjusteDetalleOut(AjusteDocenteOut):
    alias: str
    iniciales: str | None
    asignatura: AsignaturaOut | None
    cortes: list[CorteSemaforoOut]


class SemaforoAjusteOut(BaseModel):
    ajuste_id: int
    nombre_ajuste: str
    alias: str
    asignatura: AsignaturaOut | None
    semaforo_actual: str | None
    cortes: list[CorteSemaforoOut]


class SemaforoDocenteOut(BaseModel):
    resumen: dict[str, int]
    ajustes: list[SemaforoAjusteOut]


class ImplementacionOut(BaseModel):
    id: int
    ajuste_id: int
    implementado: bool
    fecha: date
    nota: str | None
    registrado_at: datetime | None


class EstrategiaImplementacionOut(BaseModel):
    id: int
    estado_implementacion: str
    implementada: bool
    nota_implementacion: str | None
    implementada_at: datetime | None
