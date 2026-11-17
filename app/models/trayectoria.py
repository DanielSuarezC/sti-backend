"""F10 - Trayectoria academica y sus 9 dimensiones de resultado (ERD §3.54-3.63) + HITO_TRAYECTORIA (v7 M8).

Nombres de tabla = nombres del ERD (`acceso`, `participacion`, `aprendizaje`, `bienestar`, `autonomia`,
`permanencia`, `progresion`, `graduacion`, `transicion_profesional`). La clase de la dimension BIENESTAR se llama
`BienestarTrayectoria` para no confundirla con PERSONAL_BIENESTAR.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    S20,
    S50,
    S100,
    S255,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    unique_active,
)
from app.models.enums import (
    BalanceVidaEstudio,
    EstadoLaboral,
    EstadoTrabajoFinal,
    IndependenciaTareas,
    NivelBajoMedioAlto,
    NivelBMA,
    ParticipacionClase,
    Satisfaccion,
    TipoHito,
    TrabajoColaborativo,
)


class TrayectoriaAcademica(Entity, Base):
    __tablename__ = "trayectoria_academica"
    __table_args__ = (
        CheckConstraint("fecha_fin_semestre IS NULL OR fecha_fin_semestre >= fecha_inicio_semestre",
                        name="ck_fechas_trayectoria"),
        unique_active("idx_trayectoria_estudiante_semestre", "estudiante_id", "semestre_academico"),
    )

    estudiante_id: Mapped[int] = fk("estudiante.id")
    semestre_academico: Mapped[S20]
    fecha_inicio_semestre: Mapped[date]
    fecha_fin_semestre: Mapped[date | None]
    asignaturas_inscritas: Mapped[int | None] = mapped_column(Integer)
    asignaturas_completadas: Mapped[int | None] = mapped_column(Integer)
    creditos_aprobados: Mapped[int | None] = mapped_column(Integer)
    promedio_academico: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))

    acceso: Mapped[list[Acceso]] = relationship(back_populates="trayectoria")
    participacion: Mapped[list[Participacion]] = relationship(back_populates="trayectoria")
    aprendizaje: Mapped[list[Aprendizaje]] = relationship(back_populates="trayectoria")
    bienestar: Mapped[list[BienestarTrayectoria]] = relationship(back_populates="trayectoria")
    autonomia: Mapped[list[Autonomia]] = relationship(back_populates="trayectoria")
    permanencia: Mapped[list[Permanencia]] = relationship(back_populates="trayectoria")
    progresion: Mapped[list[Progresion]] = relationship(back_populates="trayectoria")
    graduacion: Mapped[list[Graduacion]] = relationship(back_populates="trayectoria")
    transicion: Mapped[list[TransicionProfesional]] = relationship(back_populates="trayectoria")


class Acceso(Entity, Base):
    __tablename__ = "acceso"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    puede_ingresar_aulas: Mapped[bool] = mapped_column(default=True)
    puede_usar_biblioteca: Mapped[bool] = mapped_column(default=True)
    puede_usar_laboratorios: Mapped[bool] = mapped_column(default=True)
    puede_acceder_plataforma: Mapped[bool] = mapped_column(default=True)
    puede_usar_servicios_bienestar: Mapped[bool] = mapped_column(default=True)
    barreras_acceso_identificadas: Mapped[TXT | None]
    ajustes_acceso_implementados: Mapped[TXT | None]

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="acceso")


class Participacion(Entity, Base):
    __tablename__ = "participacion"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    asistencia_promedio: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))  # ERD: DECIMAL(3,1) -> (4,1) admite 100.0
    participacion_clase: Mapped[ParticipacionClase] = enum_col(ParticipacionClase, default=ParticipacionClase.MEDIA)
    actividades_extracurriculares: Mapped[int | None] = mapped_column(Integer)
    trabajo_colaborativo: Mapped[TrabajoColaborativo] = enum_col(
        TrabajoColaborativo, default=TrabajoColaborativo.CON_APOYO
    )
    interaccion_pares: Mapped[TXT | None]
    liderazgo_grupos: Mapped[bool] = mapped_column(default=False)

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="participacion")


class Aprendizaje(Entity, Base):
    __tablename__ = "aprendizaje"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    demuestra_competencias: Mapped[bool] = mapped_column(default=False)
    calificaciones_promedio: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    asignaturas_aprobadas_porcentaje: Mapped[int | None] = mapped_column(Integer)
    necesidad_tutoria: Mapped[bool] = mapped_column(default=False)
    mejora_academica: Mapped[TXT | None]
    aprendizajes_significativos: Mapped[TXT | None]

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="aprendizaje")


class BienestarTrayectoria(Entity, Base):
    __tablename__ = "bienestar"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    percepcion_bienestar: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    ansiedad_nivel: Mapped[NivelBMA | None] = enum_col(NivelBMA, nullable=True)
    depresion_indicadores: Mapped[bool] = mapped_column(default=False)
    siente_pertenencia: Mapped[bool] = mapped_column(default=False)
    seguridad_percibida: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    apoyo_socioafectivo: Mapped[TXT | None]
    balance_vida_estudio: Mapped[BalanceVidaEstudio] = enum_col(
        BalanceVidaEstudio, default=BalanceVidaEstudio.DESEQUILIBRADO
    )

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="bienestar")


class Autonomia(Entity, Base):
    __tablename__ = "autonomia"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    gestiona_su_agenda: Mapped[bool] = mapped_column(default=False)
    solicita_apoyos_autonomamente: Mapped[bool] = mapped_column(default=False)
    autorregulacion: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.BAJA)
    independencia_tareas_academicas: Mapped[IndependenciaTareas] = enum_col(
        IndependenciaTareas, default=IndependenciaTareas.PARCIAL_DEPENDENCIA, length=40
    )
    capacidad_resolucion_problemas: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.BAJA)
    incremento_autonomia: Mapped[TXT | None]

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="autonomia")


class Permanencia(Entity, Base):
    __tablename__ = "permanencia"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    continua_matriculado: Mapped[bool] = mapped_column(default=True)
    riesgo_desersion: Mapped[NivelBajoMedioAlto] = enum_col(NivelBajoMedioAlto, default=NivelBajoMedioAlto.BAJO)
    factores_riesgo: Mapped[TXT | None]
    factores_proteccion: Mapped[TXT | None]
    plan_retencion: Mapped[TXT | None]
    cambios_circunstancias: Mapped[TXT | None]

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="permanencia")


class Progresion(Entity, Base):
    __tablename__ = "progresion"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    semestres_completados: Mapped[int | None] = mapped_column(Integer)
    avance_plan_estudios_porcentaje: Mapped[int | None] = mapped_column(Integer)
    creditosfaltantes: Mapped[int | None] = mapped_column(Integer)
    asignaturas_pendientes: Mapped[int | None] = mapped_column(Integer)
    tiempo_estimado_graduacion: Mapped[S50 | None]
    probabilidad_graduacion: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="progresion")


class Graduacion(Entity, Base):
    __tablename__ = "graduacion"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    ha_graduado: Mapped[bool] = mapped_column(default=False)
    fecha_graduacion: Mapped[date | None]
    grado_obtenido: Mapped[S100 | None]
    estado_trabajofinal_tesis: Mapped[EstadoTrabajoFinal | None] = enum_col(EstadoTrabajoFinal, nullable=True)
    satisfaccion_formacion: Mapped[Satisfaccion | None] = enum_col(Satisfaccion, nullable=True)
    logros_academicos: Mapped[TXT | None]

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="graduacion")


class TransicionProfesional(Entity, Base):
    __tablename__ = "transicion_profesional"

    trayectoria_id: Mapped[int] = fk("trayectoria_academica.id")
    experiencia_practica_laboral: Mapped[bool] = mapped_column(default=False)
    horas_practica_laboral: Mapped[int | None] = mapped_column(Integer)
    sector_interes_profesional: Mapped[S255 | None]
    capacidades_laborales: Mapped[TXT | None]
    necesidades_apoyo_laboral: Mapped[TXT | None]
    ajustes_laborales_identificados: Mapped[TXT | None]
    estado_laboral_actual: Mapped[EstadoLaboral | None] = enum_col(EstadoLaboral, nullable=True)
    satisfaccion_laboral: Mapped[Satisfaccion | None] = enum_col(Satisfaccion, nullable=True)

    trayectoria: Mapped[TrayectoriaAcademica] = relationship(back_populates="transicion")


class HitoTrayectoria(Entity, Base):
    """Hitos de trayectoria (v7 M8): cambio de semestre, practicas, trabajo de grado, graduacion..."""

    __tablename__ = "hito_trayectoria"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    trayectoria_id: Mapped[int | None] = fk("trayectoria_academica.id", nullable=True)
    tipo_hito: Mapped[TipoHito] = enum_col(TipoHito)
    fecha_hito: Mapped[date]
    descripcion: Mapped[TXT | None]
    registrado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
