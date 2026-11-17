"""F7 - Matriz de responsabilidades: APOYO, TIPO_APOYO, RESPONSABLE_APOYO, RECURSO, IMPLEMENTACION_APOYO,
REGISTRO_IMPLEMENTACION (ERD §3.41-3.46).

Los campos LONGBLOB del ERD (`evidencia_digitalizada`) se reemplazan por una referencia al almacenamiento
(R2 / disco local): `archivo_key`, `archivo_nombre`, `archivo_content_type`, `archivo_size`.
"""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import CheckConstraint, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    DEC,
    DT,
    JSL,
    S50,
    S100,
    S200,
    S255,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    utcnow,
)
from app.models.enums import (
    CategoriaApoyo,
    DisponibilidadRecurso,
    EstadoApoyo,
    EstadoImplementacion,
    IntensidadApoyo,
    TipoEvidenciaArchivo,
    TipoRecurso,
)


class Apoyo(Entity, Base):
    __tablename__ = "apoyo"
    __table_args__ = (
        CheckConstraint("fecha_fin_prevista IS NULL OR fecha_fin_prevista >= fecha_inicio", name="ck_apoyo_fechas"),
    )

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    ajuste_id: Mapped[int | None] = fk("ajuste_razonable.id", nullable=True)
    nombre_apoyo: Mapped[S200]
    descripcion_apoyo: Mapped[TXT]
    tipo_apoyo: Mapped[S100]
    objetivo: Mapped[TXT | None]
    fecha_inicio: Mapped[date]
    fecha_fin_prevista: Mapped[date | None]
    continuidad_indefinida: Mapped[bool] = mapped_column(default=False)
    intensidad: Mapped[IntensidadApoyo] = enum_col(IntensidadApoyo, default=IntensidadApoyo.MEDIA)
    estado: Mapped[EstadoApoyo] = enum_col(EstadoApoyo, default=EstadoApoyo.PLANEADO)
    # --- slice C1 (aditivo): origen del apoyo en el plan y calendario vinculado (ids de referencia, sin FK) ---
    estrategia_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tipos: Mapped[list[TipoApoyo]] = relationship(back_populates="apoyo")
    responsables: Mapped[list[ResponsableApoyo]] = relationship(back_populates="apoyo")


class TipoApoyo(Entity, Base):
    __tablename__ = "tipo_apoyo"

    apoyo_id: Mapped[int] = fk("apoyo.id")
    categoria_apoyo: Mapped[CategoriaApoyo] = enum_col(CategoriaApoyo)

    apoyo: Mapped[Apoyo] = relationship(back_populates="tipos")


class ResponsableApoyo(Entity, Base):
    __tablename__ = "responsable_apoyo"
    __table_args__ = (
        CheckConstraint("porcentaje_dedicacion >= 0 AND porcentaje_dedicacion <= 100",
                        name="ck_responsable_apoyo_dedicacion"),
    )

    apoyo_id: Mapped[int] = fk("apoyo.id")
    usuario_responsable_id: Mapped[int] = fk("usuario.id")
    cargo_responsable: Mapped[S100 | None]
    porcentaje_dedicacion: Mapped[int] = mapped_column(Integer, default=100)
    fecha_asignacion: Mapped[date]
    fecha_fin_asignacion: Mapped[date | None]
    es_principal: Mapped[bool] = mapped_column(default=True)  # F7: responsable principal / secundario
    frecuencia: Mapped[S200 | None]

    apoyo: Mapped[Apoyo] = relationship(back_populates="responsables")
    recursos: Mapped[list[Recurso]] = relationship(back_populates="responsable_apoyo")


class Recurso(Entity, Base):
    __tablename__ = "recurso"

    responsable_apoyo_id: Mapped[int] = fk("responsable_apoyo.id")
    tipo_recurso: Mapped[TipoRecurso] = enum_col(TipoRecurso)
    descripcion_recurso: Mapped[TXT]
    cantidad: Mapped[int | None] = mapped_column(Integer)
    unidad_medida: Mapped[S50 | None]
    costo_estimado: Mapped[DEC | None]
    disponibilidad: Mapped[DisponibilidadRecurso] = enum_col(
        DisponibilidadRecurso, default=DisponibilidadRecurso.DISPONIBLE
    )
    responsable_provision_id: Mapped[int | None] = fk("usuario.id", nullable=True)

    responsable_apoyo: Mapped[ResponsableApoyo] = relationship(back_populates="recursos")


class ImplementacionApoyo(Entity, Base):
    __tablename__ = "implementacion_apoyo"
    __table_args__ = (Index("idx_implementacion_responsable_fecha", "responsable_apoyo_id", "fecha_implementacion"),)

    responsable_apoyo_id: Mapped[int] = fk("responsable_apoyo.id")
    fecha_implementacion: Mapped[date]
    hora_inicio: Mapped[time | None]
    hora_fin: Mapped[time | None]
    duracion_minutos: Mapped[int | None] = mapped_column(Integer)
    descripcion_actividad: Mapped[TXT | None]
    lugar_implementacion: Mapped[S255 | None]
    asistentes_ids: Mapped[JSL | None]  # ERD: VARCHAR(500) -> lista JSON de ids de usuario
    material_utilizado: Mapped[TXT | None]
    percepcion_estudiante: Mapped[TXT | None]
    observaciones: Mapped[TXT | None]
    estado: Mapped[EstadoImplementacion] = enum_col(EstadoImplementacion, default=EstadoImplementacion.EJECUTADA)

    registros: Mapped[list[RegistroImplementacion]] = relationship(back_populates="implementacion")


class RegistroImplementacion(Entity, Base):
    __tablename__ = "registro_implementacion"

    implementacion_id: Mapped[int] = fk("implementacion_apoyo.id")
    fecha_registro: Mapped[DT] = mapped_column(default=utcnow)
    # Archivo de evidencia en almacenamiento (reemplaza LONGBLOB del ERD)
    archivo_key: Mapped[S500 | None]
    archivo_nombre: Mapped[S255 | None]
    archivo_content_type: Mapped[S100 | None]
    archivo_size: Mapped[int | None] = mapped_column(Integer)
    tipo_evidencia: Mapped[TipoEvidenciaArchivo | None] = enum_col(TipoEvidenciaArchivo, nullable=True)
    nota: Mapped[TXT | None]
    registrado_por_id: Mapped[int] = fk("usuario.id")

    implementacion: Mapped[ImplementacionApoyo] = relationship(back_populates="registros")
