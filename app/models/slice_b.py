"""Tablas ADITIVAS del slice B (consentimiento/ARCO, F1-F2, F4-F5). Migración: 20261116_00B1_slice_b.

Por qué existen (el modelo base no las traía):

* ``consentimiento_detalle``  nombre tecleado, modalidad (autónoma/asistida), 3ª aceptación (compartir ajustes con docentes)
  y marca de la copia enviada por correo. ``consentimiento`` sigue siendo inmutable.
* ``solicitud_arco``          derechos ARCO (Ley 1581/2012, RNF-07) con plazos legales.
* ``barrera_facilitador``     vínculo N:M «el facilitador mitiga la barrera» (HU-11).
* ``historia_academica``      sección «historia académica» de F1 (la v7 §M2 la exige; el ERD no la modelaba). Cifrada.
* ``meta_estudiante``         «metas» de F2 (la v7 §M2 y el paso 2 las exigen; el ERD no las modelaba).
* ``formato_comentario``      comentarios de la persona (voz del estudiante) sobre F1/F2; no versionan el formato.
* ``perfil_fortalezas_estado`` estado de confirmación de F2 (COMPLETA/INCOMPLETA/EN_REVISION).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    CTXT,
    DT,
    S20,
    S50,
    S255,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    unique_active,
)
from app.models.enums import EstadoCaracterizacion, NivelBMA


class ModalidadFirma(StrEnum):
    AUTONOMA = "AUTONOMA"  # el propio estudiante firma desde su sesión
    ASISTIDA_BIENESTAR = "ASISTIDA_BIENESTAR"  # firma en presencia/acompañamiento de un profesional de Bienestar


class TipoArco(StrEnum):
    ACCESO = "ACCESO"
    RECTIFICACION = "RECTIFICACION"
    CANCELACION = "CANCELACION"
    OPOSICION = "OPOSICION"


class EstadoArco(StrEnum):
    RECIBIDA = "RECIBIDA"
    EN_TRAMITE = "EN_TRAMITE"
    RESUELTA = "RESUELTA"
    RECHAZADA = "RECHAZADA"


class TipoMeta(StrEnum):
    ACADEMICA = "ACADEMICA"
    PROFESIONAL = "PROFESIONAL"
    PERSONAL = "PERSONAL"


class ConsentimientoDetalle(Entity, Base):
    __tablename__ = "consentimiento_detalle"

    consentimiento_id: Mapped[int] = fk("consentimiento.id", unique=True)
    nombre_firmante: Mapped[S255]  # nombre tecleado por el estudiante al firmar
    modalidad: Mapped[ModalidadFirma] = enum_col(ModalidadFirma, default=ModalidadFirma.AUTONOMA)
    asistido_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    acepta_compartir_ajustes_docentes: Mapped[bool] = mapped_column(default=False)
    copia_enviada_at: Mapped[DT | None]


class SolicitudArco(Entity, Base):
    __tablename__ = "solicitud_arco"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    solicitante_id: Mapped[int] = fk("usuario.id")
    tipo: Mapped[TipoArco] = enum_col(TipoArco)
    descripcion: Mapped[CTXT]  # puede contener datos de salud: cifrada
    estado: Mapped[EstadoArco] = enum_col(EstadoArco, default=EstadoArco.RECIBIDA)
    fecha_limite: Mapped[date]  # plazo legal (días hábiles): consulta 10, reclamo 15
    prorrogada: Mapped[bool] = mapped_column(default=False)
    motivo_prorroga: Mapped[S500 | None]
    respuesta: Mapped[CTXT | None]
    atendida_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    atendida_at: Mapped[DT | None]


class BarreraFacilitador(Entity, Base):
    __tablename__ = "barrera_facilitador"
    __table_args__ = (unique_active("uq_barrera_facilitador", "barrera_id", "facilitador_id"),)

    barrera_id: Mapped[int] = fk("barrera_identificada.id")
    facilitador_id: Mapped[int] = fk("facilitador.id")
    nota: Mapped[S500 | None]


class HistoriaAcademica(Entity, Base):
    __tablename__ = "historia_academica"
    __table_args__ = (unique_active("uq_historia_academica_caract", "caracterizacion_id"),)

    caracterizacion_id: Mapped[int] = fk("caracterizacion.id")
    trayectoria_escolar: Mapped[CTXT | None]
    apoyos_previos: Mapped[CTXT | None]
    experiencias_exitosas: Mapped[CTXT | None]
    dificultades_previas: Mapped[CTXT | None]
    otras_observaciones: Mapped[CTXT | None]


class MetaEstudiante(Entity, Base):
    __tablename__ = "meta_estudiante"

    perfil_fortalezas_id: Mapped[int] = fk("perfil_fortalezas.id")
    tipo: Mapped[TipoMeta] = enum_col(TipoMeta, default=TipoMeta.ACADEMICA)
    descripcion: Mapped[TXT]
    plazo: Mapped[S50 | None]
    prioridad: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)


class FormatoComentario(Entity, Base):
    __tablename__ = "formato_comentario"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    formato: Mapped[S20]  # "F1" | "F2"
    seccion: Mapped[S50]
    autor_id: Mapped[int] = fk("usuario.id")
    autor_rol: Mapped[S20]
    texto: Mapped[CTXT]


class PerfilFortalezasEstado(Entity, Base):
    __tablename__ = "perfil_fortalezas_estado"
    __table_args__ = (unique_active("uq_perfil_fortalezas_estado", "perfil_fortalezas_id"),)

    perfil_fortalezas_id: Mapped[int] = fk("perfil_fortalezas.id")
    estado: Mapped[EstadoCaracterizacion] = enum_col(EstadoCaracterizacion, default=EstadoCaracterizacion.INCOMPLETA)
    confirmado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    confirmado_at: Mapped[DT | None]

