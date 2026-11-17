"""Dominio academico: PROGRAMA_ACADEMICO, MATRICULA (ERD §3.64-3.65) + ASIGNATURA, ASIGNACION_DOCENTE,
CALENDARIO_ACADEMICO, REGISTRO_INASISTENCIA (arquitectura v7 M1, M6, RF-31)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    S20,
    S50,
    S255,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    unique_active,
)
from app.models.enums import (
    Escenario,
    EstadoMatricula,
    FuenteInasistencia,
    Modalidad,
    NivelAcademico,
)


class ProgramaAcademico(Entity, Base):
    __tablename__ = "programa_academico"

    nombre_programa: Mapped[S255]
    codigo_programa: Mapped[S50] = mapped_column(unique=True)
    descripcion_programa: Mapped[TXT | None]
    nivel_academico: Mapped[NivelAcademico] = enum_col(NivelAcademico, default=NivelAcademico.PREGRADO)
    duracion_semestres: Mapped[int | None] = mapped_column(Integer)
    total_creditos: Mapped[int | None] = mapped_column(Integer)
    coordinador_programa_id: Mapped[int | None] = fk("coordinador_programa.id", nullable=True)
    facultad_responsable: Mapped[S255 | None]
    disponibilidad_ajustes_tea: Mapped[bool] = mapped_column(default=False)
    capacitacion_docentes_tea: Mapped[bool] = mapped_column(default=False)
    numero_estudiantes_tea: Mapped[int] = mapped_column(Integer, default=0)
    semestre_practicas: Mapped[int | None] = mapped_column(Integer)  # M8: alerta al iniciar el semestre de practicas


class Matricula(Entity, Base):
    __tablename__ = "matricula"
    __table_args__ = (
        unique_active("uq_matricula_estudiante_programa_semestre", "estudiante_id", "programa_academico_id",
                      "semestre_academico"),
    )

    estudiante_id: Mapped[int] = fk("estudiante.id")
    programa_academico_id: Mapped[int] = fk("programa_academico.id")
    semestre_academico: Mapped[S20]  # p.ej. "2026-II"
    fecha_matricula: Mapped[date]
    estado_matricula: Mapped[EstadoMatricula] = enum_col(EstadoMatricula, default=EstadoMatricula.ACTIVA)
    modalidad: Mapped[Modalidad] = enum_col(Modalidad, default=Modalidad.PRESENCIAL)
    numero_asignaturas: Mapped[int | None] = mapped_column(Integer)
    creditos_matriculados: Mapped[int | None] = mapped_column(Integer)


class Asignatura(Entity, Base):
    __tablename__ = "asignatura"
    __table_args__ = (unique_active("uq_asignatura_programa_codigo", "programa_id", "codigo"),)

    programa_id: Mapped[int] = fk("programa_academico.id")
    codigo: Mapped[S50]
    nombre: Mapped[S255]
    semestre_plan: Mapped[int | None] = mapped_column(Integer)  # semestre del plan de estudios
    creditos: Mapped[int | None] = mapped_column(Integer)
    escenario_predominante: Mapped[Escenario | None] = enum_col(Escenario, nullable=True)
    es_practica: Mapped[bool] = mapped_column(default=False)


class AsignacionDocente(Entity, Base):
    """Docente (perfil DOCENTE) asignado a una asignatura en un semestre: base del alcance del docente."""

    __tablename__ = "asignacion_docente"
    __table_args__ = (
        unique_active("uq_asignacion_docente_unica", "docente_id", "asignatura_id", "semestre_academico", "grupo"),
    )

    docente_id: Mapped[int] = fk("docente.id")
    asignatura_id: Mapped[int] = fk("asignatura.id")
    semestre_academico: Mapped[S20]
    grupo: Mapped[S20 | None]


class CalendarioAcademico(Entity, Base):
    """Calendario del semestre: cortes C1-C3 y umbral de inasistencia (M1)."""

    __tablename__ = "calendario_academico"
    __table_args__ = (
        CheckConstraint("fecha_fin > fecha_inicio", name="ck_calendario_academico_rango"),
        Index("ix_calendario_semestre_programa", "semestre_academico", "programa_id"),
    )

    semestre_academico: Mapped[S20]
    programa_id: Mapped[int | None] = fk("programa_academico.id", nullable=True)  # NULL = institucional
    fecha_inicio: Mapped[date]
    fecha_fin: Mapped[date]
    fecha_c1: Mapped[date]  # semana 6-7
    fecha_c2: Mapped[date]  # semana 11-12
    fecha_c3: Mapped[date]  # semana 16-17
    umbral_inasistencia: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    activo: Mapped[bool] = mapped_column(default=False)
    fecha_inicio_practicas: Mapped[date | None]  # slice A (M1): inicio de practicas del programa (alerta a Bienestar)


class RegistroInasistencia(Entity, Base):
    """Inasistencia manual (Bienestar) o importada del SIGAA (RF-31)."""

    __tablename__ = "registro_inasistencia"
    __table_args__ = (CheckConstraint("porcentaje_inasistencia >= 0 AND porcentaje_inasistencia <= 100",
                                      name="ck_registro_inasistencia_porcentaje"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    asignatura_id: Mapped[int | None] = fk("asignatura.id", nullable=True)
    semestre_academico: Mapped[S20]
    fecha_registro: Mapped[date]
    porcentaje_inasistencia: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    fuente: Mapped[FuenteInasistencia] = enum_col(FuenteInasistencia, default=FuenteInasistencia.MANUAL)
    alerta_generada: Mapped[bool] = mapped_column(default=False)
    observaciones: Mapped[TXT | None]
    registrado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
