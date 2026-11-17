"""F3 - Analisis del contexto universitario por escenarios (RF-17).

RECONCILIACION de los 8 escenarios de la v7 con las 7 subentidades del ERD
----------------------------------------------------------------------------
El ERD (diagrama §2) lista 7 subentidades: AULA, DOCENTE, EVALUACION, CAMPUS, VIRTUALIDAD, PRACTICA,
BIENESTAR (y solo detalla atributos de AULA, DOCENTE, EVALUACION y CAMPUS). La v7 (§7.1 y §12) exige
8 *escenarios*: aula, campus, virtualidad, laboratorios, practicas clinicas, practicas de salud publica,
eventos y pasantias. No son el mismo eje: DOCENTE y EVALUACION son *facetas transversales* del contexto,
no escenarios, y BIENESTAR es un servicio, no un escenario.

Decision:
  * 8 tablas, una por escenario v7: CONTEXTO_AULA, CONTEXTO_CAMPUS, CONTEXTO_VIRTUALIDAD,
    CONTEXTO_LABORATORIO, CONTEXTO_PRACTICA_CLINICA, CONTEXTO_PRACTICA_SALUD_PUBLICA, CONTEXTO_EVENTO,
    CONTEXTO_PASANTIA. AULA y CAMPUS conservan los atributos del ERD; las demas se modelan con el mismo
    patron (campos comunes `ScenarioMixin` + atributos propios).
  * CONTEXTO_DOCENTE y CONTEXTO_EVALUACION se conservan tal cual el ERD como facetas transversales
    (practicas docentes y dinamicas de evaluacion que aplican en cualquier escenario).
  * CONTEXTO_PRACTICA del ERD se divide en CLINICA y SALUD_PUBLICA (dos escenarios distintos en v7).
  * CONTEXTO_BIENESTAR del ERD (sin atributos definidos) se absorbe en CONTEXTO_CAMPUS
    (`servicios_disponibles`, `servicios_bienestar`), porque los servicios de bienestar no son un escenario.
  Total: CONTEXTO_UNIVERSITARIO + 8 escenarios + 2 facetas = 11 tablas (el ERD tenia 5 detalladas).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Integer
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
    unique_active,
)
from app.models.enums import (
    Claridad,
    DisposicionAjustes,
    Modalidad,
    ModalidadClaseVirtual,
    ModalidadPasantia,
    NivelBajoMedioAlto,
    NivelBMA,
    NivelEstructuracion,
    TiempoEvaluacion,
    TipoEvento,
    TipoLaboratorio,
)


class ContextoUniversitario(Entity, Base):
    __tablename__ = "contexto_universitario"
    __table_args__ = (unique_active("uq_contexto_estudiante_semestre", "estudiante_id", "semestre_academico"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    programa_academico_id: Mapped[int] = fk("programa_academico.id")
    semestre_academico: Mapped[S20]
    fecha_analisis: Mapped[date]
    responsable_analisis_id: Mapped[int] = fk("usuario.id")
    resumen_contextual: Mapped[TXT | None]
    factores_protectores: Mapped[TXT | None]
    factores_de_riesgo: Mapped[TXT | None]

    aulas: Mapped[list[ContextoAula]] = relationship(back_populates="contexto")
    campus: Mapped[list[ContextoCampus]] = relationship(back_populates="contexto")
    docentes: Mapped[list[ContextoDocente]] = relationship(back_populates="contexto")
    evaluaciones: Mapped[list[ContextoEvaluacion]] = relationship(back_populates="contexto")


class ScenarioMixin:
    """Campos comunes a los 8 escenarios (F3: condiciones, metodologias docentes, dinamicas de evaluacion)."""

    aplica: Mapped[bool] = mapped_column(default=True)  # el escenario aplica al estudiante este semestre
    descripcion_condiciones: Mapped[TXT | None]
    metodologias_docentes: Mapped[TXT | None]
    dinamicas_evaluacion: Mapped[TXT | None]
    observaciones: Mapped[TXT | None]


# ----------------------------------------------------------------- escenarios (8)
class ContextoAula(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_aula"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    numero_estudiantes: Mapped[int | None] = mapped_column(Integer)
    tipo_aula: Mapped[Modalidad] = enum_col(Modalidad, default=Modalidad.PRESENCIAL)
    caracteristicas_ambientales: Mapped[TXT | None]
    disponibilidad_tecnologia: Mapped[TXT | None]
    dinamica_interaccion: Mapped[TXT | None]
    nivel_estructuracion: Mapped[NivelEstructuracion] = enum_col(
        NivelEstructuracion, default=NivelEstructuracion.MEDIANAMENTE_ESTRUCTURADA
    )

    contexto: Mapped[ContextoUniversitario] = relationship(back_populates="aulas")


class ContextoCampus(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_campus"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    accesibilidad_fisica: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    disponibilidad_espacios_tranquilos: Mapped[bool] = mapped_column(default=False)
    ruido_ambiental_nivel: Mapped[NivelBajoMedioAlto] = enum_col(NivelBajoMedioAlto, default=NivelBajoMedioAlto.ALTO)
    iluminacion_caracteristica: Mapped[S255 | None]
    servicios_disponibles: Mapped[TXT | None]
    servicios_bienestar: Mapped[TXT | None]  # absorbe CONTEXTO_BIENESTAR del diagrama del ERD
    seguridad_percibida: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    facilidades_transporte: Mapped[TXT | None]

    contexto: Mapped[ContextoUniversitario] = relationship(back_populates="campus")


class ContextoVirtualidad(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_virtualidad"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    plataformas: Mapped[S500 | None]
    modalidad_clase: Mapped[ModalidadClaseVirtual | None] = enum_col(ModalidadClaseVirtual, nullable=True)
    accesibilidad_plataforma: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    camara_obligatoria: Mapped[bool] = mapped_column(default=False)
    clases_grabadas: Mapped[bool] = mapped_column(default=False)
    conectividad_estudiante: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)


class ContextoLaboratorio(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_laboratorio"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    tipo_laboratorio: Mapped[TipoLaboratorio] = enum_col(TipoLaboratorio, default=TipoLaboratorio.OTRO)
    aforo: Mapped[int | None] = mapped_column(Integer)
    ruido_nivel: Mapped[NivelBajoMedioAlto] = enum_col(NivelBajoMedioAlto, default=NivelBajoMedioAlto.MEDIO)
    olores_o_sustancias_fuertes: Mapped[bool] = mapped_column(default=False)
    trabajo_en_equipo: Mapped[bool] = mapped_column(default=True)
    protocolos_seguridad: Mapped[TXT | None]


class ContextoPracticaClinica(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_practica_clinica"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    institucion_practica: Mapped[S255 | None]
    servicio_o_area: Mapped[S200 | None]
    turnos: Mapped[S200 | None]
    duracion_turno_horas: Mapped[int | None] = mapped_column(Integer)
    rotaciones_frecuentes: Mapped[bool] = mapped_column(default=False)
    nivel_estimulos_sensoriales: Mapped[NivelBajoMedioAlto] = enum_col(
        NivelBajoMedioAlto, default=NivelBajoMedioAlto.ALTO
    )
    tutor_clinico_disponible: Mapped[bool] = mapped_column(default=True)


class ContextoPracticaSaludPublica(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_practica_salud_publica"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    entorno_o_comunidad: Mapped[S255 | None]
    trabajo_de_campo: Mapped[bool] = mapped_column(default=True)
    requiere_transporte: Mapped[bool] = mapped_column(default=True)
    interaccion_comunitaria: Mapped[NivelBajoMedioAlto] = enum_col(
        NivelBajoMedioAlto, default=NivelBajoMedioAlto.ALTO
    )
    imprevisibilidad: Mapped[NivelBajoMedioAlto] = enum_col(NivelBajoMedioAlto, default=NivelBajoMedioAlto.ALTO)
    acompanamiento_docente: Mapped[bool] = mapped_column(default=True)


class ContextoEvento(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_evento"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    tipo_evento: Mapped[TipoEvento] = enum_col(TipoEvento, default=TipoEvento.ACADEMICO)
    aforo_estimado: Mapped[int | None] = mapped_column(Integer)
    ruido_nivel: Mapped[NivelBajoMedioAlto] = enum_col(NivelBajoMedioAlto, default=NivelBajoMedioAlto.ALTO)
    programa_previsible: Mapped[bool] = mapped_column(default=False)
    posibilidad_salida_tranquila: Mapped[bool] = mapped_column(default=False)


class ContextoPasantia(ScenarioMixin, Entity, Base):
    __tablename__ = "contexto_pasantia"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    organizacion: Mapped[S255 | None]
    sector: Mapped[S200 | None]
    modalidad: Mapped[ModalidadPasantia] = enum_col(ModalidadPasantia, default=ModalidadPasantia.PRESENCIAL)
    supervisor_asignado: Mapped[bool] = mapped_column(default=False)
    flexibilidad_horaria: Mapped[bool] = mapped_column(default=False)
    ajustes_conversados_con_organizacion: Mapped[bool] = mapped_column(default=False)


# ----------------------------------------------------------------- facetas transversales (ERD §3.14-3.15)
class ContextoDocente(Entity, Base):
    __tablename__ = "contexto_docente"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    docente_id: Mapped[int | None] = fk("docente.id", nullable=True)
    nombre_docente: Mapped[S255 | None]
    estilo_pedagogico: Mapped[S255 | None]
    disponibilidad_apoyo: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    capacitacion_inclusion: Mapped[bool] = mapped_column(default=False)
    comunicacion_clara: Mapped[bool | None]
    flexibilidad_metodologica: Mapped[bool | None]
    disposicion_ajustes: Mapped[DisposicionAjustes] = enum_col(DisposicionAjustes, default=DisposicionAjustes.NEUTRA)

    contexto: Mapped[ContextoUniversitario] = relationship(back_populates="docentes")


class ContextoEvaluacion(Entity, Base):
    __tablename__ = "contexto_evaluacion"

    contexto_universitario_id: Mapped[int] = fk("contexto_universitario.id")
    tipos_evaluacion_usados: Mapped[S500 | None]
    claridad_criterios: Mapped[Claridad] = enum_col(Claridad, default=Claridad.MEDIANAMENTE_CLARA)
    claridad_instrucciones: Mapped[Claridad] = enum_col(Claridad, default=Claridad.MEDIANAMENTE_CLARA)
    tiempo_evaluacion: Mapped[TiempoEvaluacion] = enum_col(TiempoEvaluacion, default=TiempoEvaluacion.LIMITADO)
    ambiente_evaluacion: Mapped[S500 | None]
    retroalimentacion_ofrecida: Mapped[bool] = mapped_column(default=True)
    flexibilidad_formato: Mapped[bool] = mapped_column(default=False)

    contexto: Mapped[ContextoUniversitario] = relationship(back_populates="evaluaciones")
