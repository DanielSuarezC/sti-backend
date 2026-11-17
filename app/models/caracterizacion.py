"""F1 (Caracterizacion + 4 datos) y F2 (Perfil de fortalezas + 3). ERD §3.3-3.11.

Todo texto narrativo de F1 (y los datos de comunicacion/sensoriales) se cifra en reposo (AES-256-GCM).
El docente NO tiene acceso a estas tablas (matriz §12.1).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    CTXT,
    DT,
    S100,
    S200,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    unique_active,
)
from app.models.enums import (
    EstadoCaracterizacion,
    EstadoPerfil,
    IntensidadInteres,
    NivelAutonomia,
    NivelBMA,
    NivelBMAC,
    NivelConsolidacion,
    TipoEstrategiaAprendizaje,
    TipoSensorial,
)


class Caracterizacion(Entity, Base):
    __tablename__ = "caracterizacion"
    __table_args__ = (unique_active("uq_caracterizacion_estudiante_version", "estudiante_id", "version"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    fecha_caracterizacion: Mapped[date]
    profesional_responsable_id: Mapped[int] = fk("usuario.id")
    resumen_ejecutivo: Mapped[CTXT | None]  # cifrado
    autodescripcion_estudiante: Mapped[CTXT | None]  # cifrado
    participacion_estudiante: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    fecha_ultima_actualizacion: Mapped[DT | None]
    estado: Mapped[EstadoCaracterizacion] = enum_col(EstadoCaracterizacion, default=EstadoCaracterizacion.INCOMPLETA)

    datos_comunicacion: Mapped[list[DatoComunicacion]] = relationship(back_populates="caracterizacion")
    datos_autonomia: Mapped[list[DatoAutonomia]] = relationship(back_populates="caracterizacion")
    datos_sensoriales: Mapped[list[DatoSensorial]] = relationship(back_populates="caracterizacion")
    datos_preferencia: Mapped[list[DatoPreferencia]] = relationship(back_populates="caracterizacion")


class DatoComunicacion(Entity, Base):
    __tablename__ = "dato_comunicacion"

    caracterizacion_id: Mapped[int] = fk("caracterizacion.id")
    tipo_comunicacion: Mapped[S100]
    descripcion: Mapped[CTXT]
    fortalezas_comunicacion: Mapped[CTXT | None]
    dificultades_comunicacion: Mapped[CTXT | None]
    estrategias_favorables: Mapped[CTXT | None]

    caracterizacion: Mapped[Caracterizacion] = relationship(back_populates="datos_comunicacion")


class DatoAutonomia(Entity, Base):
    __tablename__ = "dato_autonomia"

    caracterizacion_id: Mapped[int] = fk("caracterizacion.id")
    contexto_autonomia: Mapped[S100]
    nivel_autonomia: Mapped[NivelAutonomia] = enum_col(NivelAutonomia)
    actividades_autonomas: Mapped[CTXT | None]
    actividades_con_apoyo: Mapped[CTXT | None]
    actividades_supervisadas: Mapped[CTXT | None]

    caracterizacion: Mapped[Caracterizacion] = relationship(back_populates="datos_autonomia")


class DatoSensorial(Entity, Base):
    __tablename__ = "dato_sensorial"

    caracterizacion_id: Mapped[int] = fk("caracterizacion.id")
    tipo_sensorial: Mapped[TipoSensorial] = enum_col(TipoSensorial)
    hipersensibilidad: Mapped[bool | None]
    hiposensibilidad: Mapped[bool | None]
    descripcion_experiencia: Mapped[CTXT | None]
    impacto_academico: Mapped[CTXT | None]
    estrategias_autoregulacion: Mapped[CTXT | None]

    caracterizacion: Mapped[Caracterizacion] = relationship(back_populates="datos_sensoriales")


class DatoPreferencia(Entity, Base):
    __tablename__ = "dato_preferencia"

    caracterizacion_id: Mapped[int] = fk("caracterizacion.id")
    tipo_preferencia: Mapped[S100]
    descripcion: Mapped[CTXT]
    prioridad: Mapped[NivelBMAC] = enum_col(NivelBMAC, default=NivelBMAC.MEDIA)
    razon_preferencia: Mapped[CTXT | None]

    caracterizacion: Mapped[Caracterizacion] = relationship(back_populates="datos_preferencia")


# ----------------------------------------------------------------- F2
class PerfilFortalezas(Entity, Base):
    __tablename__ = "perfil_fortalezas"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    fecha_elaboracion: Mapped[date]
    profesional_responsable_id: Mapped[int] = fk("usuario.id")
    narrativa_fortalezas: Mapped[TXT | None]
    narrativa_intereses: Mapped[TXT | None]
    narrativa_estrategias: Mapped[TXT | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[EstadoPerfil] = enum_col(EstadoPerfil, default=EstadoPerfil.ACTIVO)

    fortalezas: Mapped[list[Fortaleza]] = relationship(back_populates="perfil")
    intereses: Mapped[list[Interes]] = relationship(back_populates="perfil")
    estrategias: Mapped[list[EstrategiaAprendizaje]] = relationship(back_populates="perfil")


class Fortaleza(Entity, Base):
    __tablename__ = "fortaleza"

    perfil_fortalezas_id: Mapped[int] = fk("perfil_fortalezas.id")
    nombre_fortaleza: Mapped[S200]
    descripcion_detallada: Mapped[TXT]
    areas_aplicacion: Mapped[S500 | None]
    nivel_consolidacion: Mapped[NivelConsolidacion] = enum_col(
        NivelConsolidacion, default=NivelConsolidacion.CONSOLIDADA
    )

    perfil: Mapped[PerfilFortalezas] = relationship(back_populates="fortalezas")


class Interes(Entity, Base):
    __tablename__ = "interes"

    perfil_fortalezas_id: Mapped[int] = fk("perfil_fortalezas.id")
    nombre_interes: Mapped[S200]
    descripcion: Mapped[TXT]
    intensidad: Mapped[IntensidadInteres] = enum_col(IntensidadInteres, default=IntensidadInteres.MODERADO)
    aplicacion_academica: Mapped[TXT | None]
    aplicacion_laboral: Mapped[TXT | None]

    perfil: Mapped[PerfilFortalezas] = relationship(back_populates="intereses")


class EstrategiaAprendizaje(Entity, Base):
    __tablename__ = "estrategia_aprendizaje"

    perfil_fortalezas_id: Mapped[int] = fk("perfil_fortalezas.id")
    nombre_estrategia: Mapped[S200]
    descripcion: Mapped[TXT]
    tipo_estrategia: Mapped[TipoEstrategiaAprendizaje] = enum_col(TipoEstrategiaAprendizaje)
    efectividad_reportada: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.ALTA)
    contextos_aplicacion: Mapped[TXT | None]

    perfil: Mapped[PerfilFortalezas] = relationship(back_populates="estrategias")
