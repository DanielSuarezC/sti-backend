"""Consentimiento y acceso: CONSENTIMIENTO (F0), AUTORIZACION_FAMILIAR, SOLICITUD_INGRESO (Via 2),
CUESTIONARIO_AQ10 y RESPUESTA_AQ10 (tamizaje)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, Integer, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedJSON
from app.models.base import (
    DT,
    JSL,
    S20,
    S50,
    S100,
    S255,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
)
from app.models.enums import (
    AlcanceFamiliar,
    EstadoAutorizacionFamiliar,
    EstadoConsentimiento,
    EstadoSolicitudIngreso,
    ModalidadAQ10,
)


class Consentimiento(Entity, Base):
    """F0: consentimiento informado firmado digitalmente con sello de tiempo (RF-05, RF-06, RF-07).

    El registro es inmutable: solo pueden cambiar los campos de revocacion (ver guardia ORM abajo).
    """

    __tablename__ = "consentimiento"
    __table_args__ = (Index("ix_consentimiento_estudiante_estado", "estudiante_id", "estado"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    version_texto: Mapped[S20]  # version del texto legal F0 firmado
    texto_hash: Mapped[S100]  # SHA-256 del texto mostrado
    acepta_tratamiento_datos_sensibles: Mapped[bool] = mapped_column(default=False)
    acepta_politica_privacidad: Mapped[bool] = mapped_column(default=False)
    firmado_at: Mapped[DT]
    firma_hash: Mapped[S100]  # SHA-256(estudiante|version|texto_hash|firmado_at)
    firmado_por_id: Mapped[int] = fk("usuario.id")
    ip: Mapped[S50 | None]
    user_agent: Mapped[S255 | None]
    estado: Mapped[EstadoConsentimiento] = enum_col(EstadoConsentimiento, default=EstadoConsentimiento.FIRMADO)
    revocado_at: Mapped[DT | None]
    motivo_revocacion: Mapped[TXT | None]


_CONSENT_MUTABLE = {"estado", "revocado_at", "motivo_revocacion", "updated_at", "deleted_at", "deleted_by_id",
                    "deleted_reason"}


class ConsentimientoInmutableError(RuntimeError):
    pass


@event.listens_for(Consentimiento, "before_update")
def _consentimiento_inmutable(mapper, connection, target):
    state = inspect(target)
    for attr in state.attrs:
        if attr.key in _CONSENT_MUTABLE:
            continue
        if attr.history.has_changes():
            raise ConsentimientoInmutableError(
                f"El consentimiento firmado es inmutable (campo '{attr.key}'). Solo puede revocarse."
            )


class AutorizacionFamiliar(Entity, Base):
    """Autorizacion del estudiante a un familiar con alcance y revocacion (arquitectura v7 §4.1)."""

    __tablename__ = "autorizacion_familiar"
    __table_args__ = (Index("ix_autfam_estudiante_estado", "estudiante_id", "estado"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    familiar_usuario_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    familiar_nombre: Mapped[S255]
    familiar_email: Mapped[S255] = mapped_column(index=True)
    parentesco: Mapped[S100 | None]
    alcance: Mapped[JSL]  # lista de AlcanceFamiliar
    estado: Mapped[EstadoAutorizacionFamiliar] = enum_col(
        EstadoAutorizacionFamiliar, default=EstadoAutorizacionFamiliar.PENDIENTE
    )
    otorgada_at: Mapped[DT]
    expira_at: Mapped[DT | None]
    revocada_at: Mapped[DT | None]
    motivo_revocacion: Mapped[TXT | None]

    def permite(self, alcance: AlcanceFamiliar | str) -> bool:
        from app.models.base import utcnow

        if self.estado not in (EstadoAutorizacionFamiliar.VIGENTE, EstadoAutorizacionFamiliar.PENDIENTE):
            return False
        if self.revocada_at is not None:
            return False
        if self.expira_at is not None and self.expira_at <= utcnow():
            return False
        return str(alcance) in (self.alcance or [])


class SolicitudIngreso(Entity, Base):
    """Via 2: solicitud publica de ingreso, aprobada por Bienestar (arquitectura v7 §4.2)."""

    __tablename__ = "solicitud_ingreso"

    codigo_estudiantil: Mapped[S50] = mapped_column(index=True)
    email_institucional: Mapped[S255] = mapped_column(index=True)
    nombre_completo: Mapped[S255]
    telefono: Mapped[S20 | None]
    programa_id: Mapped[int | None] = fk("programa_academico.id", nullable=True)
    estado: Mapped[EstadoSolicitudIngreso] = enum_col(
        EstadoSolicitudIngreso, default=EstadoSolicitudIngreso.PENDIENTE
    )
    verificada_directorio: Mapped[bool] = mapped_column(default=False)  # codigo existe en directorio (SSO/matricula)
    acepta_aviso_privacidad: Mapped[bool] = mapped_column(default=False)
    ip: Mapped[S50 | None]
    revisado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    revisado_at: Mapped[DT | None]
    motivo_rechazo: Mapped[TXT | None]
    usuario_creado_id: Mapped[int | None] = fk("usuario.id", nullable=True)


class CuestionarioAQ10(Entity, Base):
    """Configuracion del AQ-10 (RF-08): items, opciones, logica de puntuacion y punto de corte."""

    __tablename__ = "cuestionario_aq10"

    nombre: Mapped[S255]
    version: Mapped[S20]
    idioma: Mapped[S20] = mapped_column(default="es-CO")
    fuente: Mapped[S500 | None]  # p. ej. Allison, Auyeung & Baron-Cohen (2012)
    # [{"numero":1,"texto":"...","puntua_si":"ACUERDO"|"DESACUERDO"}, ...]
    items: Mapped[JSL]
    # [{"valor":1,"etiqueta":"Totalmente de acuerdo","tipo":"ACUERDO"}, ...] (Likert de 4 puntos)
    opciones: Mapped[JSL]
    punto_corte: Mapped[int] = mapped_column(Integer, default=6)
    revision_linguistica_pendiente: Mapped[bool] = mapped_column(default=True)
    activo: Mapped[bool] = mapped_column(default=False)


class RespuestaAQ10(Entity, Base):
    """Aplicacion del AQ-10. Respuestas y puntaje CIFRADOS (AES-256-GCM). Nunca viaja a servicios de IA."""

    __tablename__ = "respuesta_aq10"
    __table_args__ = (Index("ix_respuesta_aq10_estudiante_fecha", "estudiante_id", "aplicado_at"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    cuestionario_id: Mapped[int] = fk("cuestionario_aq10.id")
    aplicado_por_id: Mapped[int] = fk("usuario.id")
    modalidad: Mapped[ModalidadAQ10] = enum_col(ModalidadAQ10)
    aplicado_at: Mapped[DT]
    respuestas: Mapped[Any] = mapped_column(EncryptedJSON(), nullable=False)  # {"1": 1..4, ...}
    puntaje: Mapped[Any] = mapped_column(EncryptedJSON(), nullable=False)  # entero 0-10 cifrado
    punto_corte_aplicado: Mapped[int] = mapped_column(Integer)
    # Booleano en claro, necesario para el flujo (RF-10) y para filtrar pendientes sin descifrar.
    supera_umbral: Mapped[bool] = mapped_column(default=False)
    flujo_activado: Mapped[bool] = mapped_column(default=False)
