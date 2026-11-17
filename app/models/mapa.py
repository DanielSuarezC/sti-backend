"""F4 - Mapa de barreras (BARRERA_IDENTIFICADA + 8 subtipos) y F5 - Mapa de facilitadores
(FACILITADOR + 5 subtipos). ERD §3.17-3.31.

Las subentidades se modelan como tablas de detalle 1:N (ERD) enlazadas por `barrera_id` / `facilitador_id`;
`tipo_barrera` y `tipo_facilitador` pasan de VARCHAR libre a ENUM (8 y 5 valores de la v7).
Se agrega `escenario` a la barrera (v7 M4: "registro por tipo y escenario").
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    S20,
    S200,
    S255,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
)
from app.models.enums import (
    AspectoEvaluativo,
    DisponibilidadTecnologia,
    Escenario,
    EstadoBarrera,
    Frecuencia,
    IntensidadFacilitador,
    OrigenPercibido,
    Renovabilidad,
    Severidad,
    TipoActitud,
    TipoBarrera,
    TipoFacilitador,
    TipoRelacionSocial,
    TipoSensorial,
)


class BarreraIdentificada(Entity, Base):
    __tablename__ = "barrera_identificada"
    __table_args__ = (
        Index("idx_barrera_tipo", "tipo_barrera", "frecuencia"),
        Index("idx_barrera_estudiante", "estudiante_id", "fecha_identificacion"),
    )

    estudiante_id: Mapped[int] = fk("estudiante.id")
    tipo_barrera: Mapped[TipoBarrera] = enum_col(TipoBarrera)
    escenario: Mapped[Escenario | None] = enum_col(Escenario, nullable=True)
    descripcion_barrera: Mapped[TXT]
    contexto_aparicion: Mapped[S500 | None]
    frecuencia: Mapped[Frecuencia] = enum_col(Frecuencia, default=Frecuencia.FRECUENTE)
    severidad: Mapped[Severidad] = enum_col(Severidad, default=Severidad.MODERADA)
    impacto_participacion: Mapped[bool] = mapped_column(default=False)
    impacto_aprendizaje: Mapped[bool] = mapped_column(default=False)
    impacto_bienestar: Mapped[bool] = mapped_column(default=False)
    impacto_permanencia: Mapped[bool] = mapped_column(default=False)
    origen_percibido: Mapped[OrigenPercibido | None] = enum_col(OrigenPercibido, nullable=True)
    fecha_identificacion: Mapped[date]
    estado: Mapped[EstadoBarrera] = enum_col(EstadoBarrera, default=EstadoBarrera.IDENTIFICADA)
    semestre_academico: Mapped[S20 | None]
    registrada_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)

    actitudinales: Mapped[list[BarreraActitudinal]] = relationship(back_populates="barrera")
    comunicativas: Mapped[list[BarreraComunicativa]] = relationship(back_populates="barrera")
    pedagogicas: Mapped[list[BarreraPedagogica]] = relationship(back_populates="barrera")
    evaluativas: Mapped[list[BarreraEvaluativa]] = relationship(back_populates="barrera")
    sensoriales: Mapped[list[BarreraSensorial]] = relationship(back_populates="barrera")
    sociales: Mapped[list[BarreraSocial]] = relationship(back_populates="barrera")
    institucionales: Mapped[list[BarreraInstitucional]] = relationship(back_populates="barrera")
    tecnologicas: Mapped[list[BarreraTecnologica]] = relationship(back_populates="barrera")


class BarreraActitudinal(Entity, Base):
    __tablename__ = "barrera_actitudinal"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    actores_implicados: Mapped[S500 | None]
    tipo_actitud: Mapped[TipoActitud | None] = enum_col(TipoActitud, nullable=True)
    evidencia: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="actitudinales")


class BarreraComunicativa(Entity, Base):
    __tablename__ = "barrera_comunicativa"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    tipo_comunicacion_problema: Mapped[S255 | None]
    descripcion_problema: Mapped[TXT | None]
    consecuencias: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="comunicativas")


class BarreraPedagogica(Entity, Base):
    __tablename__ = "barrera_pedagogica"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    metodologia_problematica: Mapped[S255 | None]
    razon_problema: Mapped[TXT | None]
    alternativas_exitosas: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="pedagogicas")


class BarreraEvaluativa(Entity, Base):
    __tablename__ = "barrera_evaluativa"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    aspecto_evaluativo: Mapped[AspectoEvaluativo | None] = enum_col(AspectoEvaluativo, nullable=True)
    descripcion_problema: Mapped[TXT | None]
    impacto_calificaciones: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="evaluativas")


class BarreraSensorial(Entity, Base):
    __tablename__ = "barrera_sensorial"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    tipo_sensorial: Mapped[TipoSensorial] = enum_col(TipoSensorial)
    hipersensibilidad: Mapped[bool | None]
    hiposensibilidad: Mapped[bool | None]
    estimulos_problematicos: Mapped[TXT | None]
    impacto_en_clase: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="sensoriales")


class BarreraSocial(Entity, Base):
    __tablename__ = "barrera_social"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    tipo_interaccion: Mapped[S255 | None]
    descripcion_dificultad: Mapped[TXT | None]
    consecuencias_sociales: Mapped[TXT | None]
    # RF-19: toda barrera social requiere al menos una propuesta de respuesta INSTITUCIONAL (validado en servicio)
    propuesta_respuesta_institucional: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="sociales")


class BarreraInstitucional(Entity, Base):
    __tablename__ = "barrera_institucional"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    politica_procedimiento: Mapped[S500 | None]
    impacto_acceso: Mapped[bool] = mapped_column(default=False)
    impacto_permanencia: Mapped[bool] = mapped_column(default=False)
    sugerencia_cambio: Mapped[TXT | None]

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="institucionales")


class BarreraTecnologica(Entity, Base):
    __tablename__ = "barrera_tecnologica"

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    tipo_tecnologia: Mapped[S255 | None]
    problema_especifico: Mapped[TXT | None]
    disponibilidad_alternativas: Mapped[bool] = mapped_column(default=False)

    barrera: Mapped[BarreraIdentificada] = relationship(back_populates="tecnologicas")


# ----------------------------------------------------------------- F5
class Facilitador(Entity, Base):
    __tablename__ = "facilitador"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    tipo_facilitador: Mapped[TipoFacilitador] = enum_col(TipoFacilitador)
    nombre_facilitador: Mapped[S200]
    descripcion_detallada: Mapped[TXT]
    contextos_donde_opera: Mapped[S500 | None]
    intensidad_impacto: Mapped[IntensidadFacilitador] = enum_col(
        IntensidadFacilitador, default=IntensidadFacilitador.MODERADA
    )
    renovabilidad: Mapped[Renovabilidad] = enum_col(Renovabilidad, default=Renovabilidad.FIJO)
    fecha_identificacion: Mapped[date]
    potencial_de_uso: Mapped[TXT | None]  # v7 M4: "descripcion y potencial de uso"
    registrado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)

    personales: Mapped[list[FacilitadorPersonal]] = relationship(back_populates="facilitador")
    pedagogicos: Mapped[list[FacilitadorPedagogico]] = relationship(back_populates="facilitador")
    sociales: Mapped[list[FacilitadorSocial]] = relationship(back_populates="facilitador")
    institucionales: Mapped[list[FacilitadorInstitucional]] = relationship(back_populates="facilitador")
    tecnologicos: Mapped[list[FacilitadorTecnologico]] = relationship(back_populates="facilitador")


class FacilitadorPersonal(Entity, Base):
    __tablename__ = "facilitador_personal"

    facilitador_id: Mapped[int] = fk("facilitador.id")
    caracteristica_personal: Mapped[S255 | None]
    evidencia_fortaleza: Mapped[TXT | None]

    facilitador: Mapped[Facilitador] = relationship(back_populates="personales")


class FacilitadorPedagogico(Entity, Base):
    __tablename__ = "facilitador_pedagogico"

    facilitador_id: Mapped[int] = fk("facilitador.id")
    tipo_estrategia: Mapped[S255 | None]
    docentes_que_usan: Mapped[S500 | None]

    facilitador: Mapped[Facilitador] = relationship(back_populates="pedagogicos")


class FacilitadorSocial(Entity, Base):
    __tablename__ = "facilitador_social"

    facilitador_id: Mapped[int] = fk("facilitador.id")
    tipo_relacion: Mapped[TipoRelacionSocial | None] = enum_col(TipoRelacionSocial, nullable=True)
    actores_implicados: Mapped[S500 | None]

    facilitador: Mapped[Facilitador] = relationship(back_populates="sociales")


class FacilitadorInstitucional(Entity, Base):
    __tablename__ = "facilitador_institucional"

    facilitador_id: Mapped[int] = fk("facilitador.id")
    politica_recurso: Mapped[S255 | None]
    accesibilidad_actual: Mapped[S500 | None]

    facilitador: Mapped[Facilitador] = relationship(back_populates="institucionales")


class FacilitadorTecnologico(Entity, Base):
    __tablename__ = "facilitador_tecnologico"

    facilitador_id: Mapped[int] = fk("facilitador.id")
    tipo_tecnologia: Mapped[S255 | None]
    funcionalidad_apoyo: Mapped[TXT | None]
    disponibilidad: Mapped[DisponibilidadTecnologia | None] = enum_col(DisponibilidadTecnologia, nullable=True)

    facilitador: Mapped[Facilitador] = relationship(back_populates="tecnologicos")
