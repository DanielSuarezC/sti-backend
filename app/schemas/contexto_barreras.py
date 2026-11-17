"""Schemas de F3 (contexto), F4 (barreras) y F5 (facilitadores).

Los esquemas por escenario / por tipo de barrera / por tipo de facilitador se derivan de las columnas de las tablas
(`model_schema`), de modo que el contrato de la API y el modelo de datos no se desalinean.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, create_model
from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy import Enum as SAEnum

from app.models.contexto import (
    ContextoAula,
    ContextoCampus,
    ContextoDocente,
    ContextoEvaluacion,
    ContextoEvento,
    ContextoLaboratorio,
    ContextoPasantia,
    ContextoPracticaClinica,
    ContextoPracticaSaludPublica,
    ContextoVirtualidad,
)
from app.models.enums import (
    Escenario,
    Frecuencia,
    OrigenPercibido,
    Severidad,
    TipoBarrera,
    TipoFacilitador,
)
from app.models.enums import IntensidadFacilitador as _IF  # noqa: F401
from app.models.enums import Renovabilidad as _R  # noqa: F401
from app.models.mapa import (
    BarreraActitudinal,
    BarreraComunicativa,
    BarreraEvaluativa,
    BarreraInstitucional,
    BarreraPedagogica,
    BarreraSensorial,
    BarreraSocial,
    BarreraTecnologica,
    FacilitadorInstitucional,
    FacilitadorPedagogico,
    FacilitadorPersonal,
    FacilitadorSocial,
    FacilitadorTecnologico,
)

_EXCL = {"id", "created_at", "updated_at", "deleted_at", "deleted_reason", "deleted_by_id",
         "contexto_universitario_id", "barrera_id", "facilitador_id"}


def _py_type(col) -> Any:
    t = col.type
    if isinstance(t, SAEnum):
        return t.enum_class
    if isinstance(t, Boolean):
        return bool
    if isinstance(t, Integer):
        return int
    if isinstance(t, Date):
        return dt.date
    return str


def model_schema(name: str, sa_model: type, *, partial: bool = False) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for c in sa_model.__table__.columns:
        if c.key in _EXCL:
            continue
        py = _py_type(c)
        kw: dict[str, Any] = {}
        if isinstance(c.type, (String, Text)) and getattr(c.type, "length", None):
            kw["max_length"] = c.type.length
        required = (not c.nullable) and c.default is None and not partial
        if required:
            fields[c.key] = (py, Field(..., **kw))
        else:
            fields[c.key] = (py | None, Field(None, **kw))
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


# ------------------------------------------------------------------ F3
ESCENARIO_MODELOS: dict[Escenario, type] = {
    Escenario.AULA: ContextoAula, Escenario.CAMPUS: ContextoCampus, Escenario.VIRTUALIDAD: ContextoVirtualidad,
    Escenario.LABORATORIOS: ContextoLaboratorio, Escenario.PRACTICA_CLINICA: ContextoPracticaClinica,
    Escenario.PRACTICA_SALUD_PUBLICA: ContextoPracticaSaludPublica, Escenario.EVENTOS: ContextoEvento,
    Escenario.PASANTIAS: ContextoPasantia,
}
ESCENARIO_NOMBRES = {
    Escenario.AULA: "Aula teórica", Escenario.CAMPUS: "Campus físico", Escenario.VIRTUALIDAD: "Virtualidad",
    Escenario.LABORATORIOS: "Laboratorios", Escenario.PRACTICA_CLINICA: "Prácticas clínicas",
    Escenario.PRACTICA_SALUD_PUBLICA: "Prácticas de salud pública", Escenario.EVENTOS: "Eventos universitarios",
    Escenario.PASANTIAS: "Pasantías",
}
ESCENARIO_IN: dict[Escenario, type[BaseModel]] = {
    e: model_schema(f"Escenario{e.title().replace('_', '')}In", m, partial=True) for e, m in ESCENARIO_MODELOS.items()
}
DocenteCtxIn = model_schema("ContextoDocenteItem", ContextoDocente)
EvaluacionCtxIn = model_schema("ContextoEvaluacionIn", ContextoEvaluacion, partial=True)


class DocenteCtxItem(DocenteCtxIn):  # type: ignore[valid-type,misc]
    id: int | None = None


class DocentesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[DocenteCtxItem] = Field(default_factory=list)
    quitar: list[int] = Field(default_factory=list)


class ContextoCrearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semestre_academico: str = Field(description="Formato AAAA-I o AAAA-II, p. ej. 2026-II")
    precargar: bool = Field(default=True, description="Precargar desde el semestre anterior / F10 si existe")


class ContextoResumenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resumen_contextual: str | None = None
    factores_protectores: str | None = None
    factores_de_riesgo: str | None = None


# ------------------------------------------------------------------ F4
BARRERA_MODELOS: dict[TipoBarrera, type] = {
    TipoBarrera.ACTITUDINAL: BarreraActitudinal, TipoBarrera.COMUNICATIVA: BarreraComunicativa,
    TipoBarrera.PEDAGOGICA: BarreraPedagogica, TipoBarrera.EVALUATIVA: BarreraEvaluativa,
    TipoBarrera.SENSORIAL: BarreraSensorial, TipoBarrera.SOCIAL: BarreraSocial,
    TipoBarrera.INSTITUCIONAL: BarreraInstitucional, TipoBarrera.TECNOLOGICA: BarreraTecnologica,
}
BARRERA_DETALLE_IN = {t: model_schema(f"Detalle{t.title()}", m) for t, m in BARRERA_MODELOS.items()}
BARRERA_DETALLE_PATCH = {t: model_schema(f"Detalle{t.title()}Patch", m, partial=True) for t, m in BARRERA_MODELOS.items()}

FACILITADOR_MODELOS: dict[TipoFacilitador, type] = {
    TipoFacilitador.PERSONAL: FacilitadorPersonal, TipoFacilitador.PEDAGOGICO: FacilitadorPedagogico,
    TipoFacilitador.SOCIAL: FacilitadorSocial, TipoFacilitador.INSTITUCIONAL: FacilitadorInstitucional,
    TipoFacilitador.TECNOLOGICO: FacilitadorTecnologico,
}
FACILITADOR_DETALLE_IN = {t: model_schema(f"DetalleFac{t.title()}", m) for t, m in FACILITADOR_MODELOS.items()}
FACILITADOR_DETALLE_PATCH = {t: model_schema(f"DetalleFac{t.title()}Patch", m, partial=True) for t, m in FACILITADOR_MODELOS.items()}


class BarreraIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tipo_barrera: TipoBarrera = Field(validation_alias=AliasChoices("tipo_barrera", "tipo"))
    escenario: Escenario | None = None
    descripcion_barrera: str = Field(min_length=3)
    contexto_aparicion: str | None = Field(default=None, max_length=500)
    frecuencia: Frecuencia = Frecuencia.FRECUENTE
    severidad: Severidad = Severidad.MODERADA
    impacto_participacion: bool = False
    impacto_aprendizaje: bool = False
    impacto_bienestar: bool = False
    impacto_permanencia: bool = False
    origen_percibido: OrigenPercibido | None = None
    fecha_identificacion: dt.date | None = None
    semestre_academico: str | None = Field(default=None, max_length=20)
    detalle: dict[str, Any] = Field(default_factory=dict, description="Campos específicos del tipo (ver GET /mapa/catalogos)")


class BarreraPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escenario: Escenario | None = None
    descripcion_barrera: str | None = Field(default=None, min_length=3)
    contexto_aparicion: str | None = Field(default=None, max_length=500)
    frecuencia: Frecuencia | None = None
    severidad: Severidad | None = None
    impacto_participacion: bool | None = None
    impacto_aprendizaje: bool | None = None
    impacto_bienestar: bool | None = None
    impacto_permanencia: bool | None = None
    origen_percibido: OrigenPercibido | None = None
    fecha_identificacion: dt.date | None = None
    semestre_academico: str | None = Field(default=None, max_length=20)
    detalle: dict[str, Any] | None = None


class PersistenteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observacion: str | None = Field(default=None, max_length=1000, description="Por qué persiste tras aplicar DUA")


# ------------------------------------------------------------------ F5
class FacilitadorIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tipo_facilitador: TipoFacilitador = Field(validation_alias=AliasChoices("tipo_facilitador", "tipo"))
    nombre_facilitador: str = Field(min_length=2, max_length=200)
    descripcion_detallada: str = Field(min_length=3)
    contextos_donde_opera: str | None = Field(default=None, max_length=500)
    intensidad_impacto: _IF = _IF.MODERADA
    renovabilidad: _R = _R.FIJO
    fecha_identificacion: dt.date | None = None
    potencial_de_uso: str | None = None
    detalle: dict[str, Any] = Field(default_factory=dict)
    barreras_mitigadas: list[int] = Field(default_factory=list, description="ids de barreras del mismo estudiante que mitiga")


class FacilitadorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre_facilitador: str | None = Field(default=None, min_length=2, max_length=200)
    descripcion_detallada: str | None = Field(default=None, min_length=3)
    contextos_donde_opera: str | None = Field(default=None, max_length=500)
    intensidad_impacto: _IF | None = None
    renovabilidad: _R | None = None
    fecha_identificacion: dt.date | None = None
    potencial_de_uso: str | None = None
    detalle: dict[str, Any] | None = None
    barreras_mitigadas: list[int] | None = Field(default=None, description="Si se envía, REEMPLAZA los vínculos")


class VinculosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barrera_ids: list[int]


def describe(schema: type[BaseModel]) -> list[dict[str, Any]]:
    """Lista de campos (nombre, tipo, requerido, valores permitidos) para `GET /mapa/catalogos`."""
    out = []
    for name, f in schema.model_fields.items():
        ann = f.annotation
        args = [a for a in getattr(ann, "__args__", ()) if a is not type(None)] or [ann]
        base = args[0]
        valores = [m.value for m in base] if isinstance(base, type) and issubclass(base, Enum) else None
        tipo = "enum" if valores else getattr(base, "__name__", str(base))
        out.append({"campo": name, "tipo": tipo, "requerido": f.is_required(), "valores": valores,
                    "max_length": next((m.max_length for m in f.metadata if hasattr(m, "max_length")), None)})
    return out
