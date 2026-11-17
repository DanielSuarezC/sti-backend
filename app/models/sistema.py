"""Sistema: PARAMETRO_SISTEMA, NOTIFICACION, EMAIL_OUTBOX, EXPORTACION y LOG_AUDITORIA (append-only)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, Integer, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import (
    DT,
    JS,
    JSON_T,
    S20,
    S50,
    S100,
    S255,
    S500,
    S1000,
    TXT,
    Base,
    Entity,
    IdMixin,
    UTCDateTime,
    enum_col,
    fk,
    utcnow,
)
from app.models.enums import (
    EstadoEmail,
    EstadoExportacion,
    TipoExportacion,
    TipoParametro,
)


class ParametroSistema(Entity, Base):
    """Parametros configurables (M1): punto de corte AQ-10, umbral de inasistencia, max. ciclos de negociacion..."""

    __tablename__ = "parametro_sistema"

    clave: Mapped[S100] = mapped_column(unique=True)
    valor: Mapped[Any] = mapped_column(JSON_T, nullable=True)
    tipo: Mapped[TipoParametro] = enum_col(TipoParametro, default=TipoParametro.TEXTO)
    descripcion: Mapped[S500 | None]
    editable: Mapped[bool] = mapped_column(default=True)


class Notificacion(Entity, Base):
    """Notificacion in-app ("push"): contrato con el frontend {id,tipo,titulo,mensaje,leida,created_at,enlace}."""

    __tablename__ = "notificacion"
    __table_args__ = (Index("ix_notificacion_usuario_leida", "usuario_id", "leida", "created_at"),)

    usuario_id: Mapped[int] = fk("usuario.id")
    tipo: Mapped[S100]  # valor de `services.notifications.Evento`
    titulo: Mapped[S255]
    mensaje: Mapped[TXT]
    enlace: Mapped[S500 | None]
    leida: Mapped[bool] = mapped_column(default=False)
    leida_at: Mapped[DT | None]
    payload: Mapped[JS | None]  # datos NO sensibles del evento (ids, cortes...)
    dedupe_key: Mapped[S255 | None] = mapped_column(index=True)  # evita duplicados (p. ej. recordatorios diarios)


class EmailOutbox(Entity, Base):
    """Cola de correo. Si no hay SMTP queda registrada (estado OMITIDO) y en logs."""

    __tablename__ = "email_outbox"
    __table_args__ = (Index("ix_email_outbox_estado", "estado", "created_at"),)

    usuario_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    notificacion_id: Mapped[int | None] = fk("notificacion.id", nullable=True)
    destinatario_email: Mapped[S255]
    asunto: Mapped[S255]
    cuerpo_texto: Mapped[TXT]
    cuerpo_html: Mapped[TXT | None]
    evento: Mapped[S100 | None]
    dedupe_key: Mapped[S255 | None] = mapped_column(index=True)
    estado: Mapped[EstadoEmail] = enum_col(EstadoEmail, default=EstadoEmail.PENDIENTE)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_error: Mapped[S1000 | None]
    enviado_at: Mapped[DT | None]


class Exportacion(Entity, Base):
    """Exportacion asincrona (PDF/Word/Excel/ARCO). El archivo vive en almacenamiento (R2/disco)."""

    __tablename__ = "exportacion"

    solicitada_por_id: Mapped[int] = fk("usuario.id")
    tipo: Mapped[TipoExportacion] = enum_col(TipoExportacion)
    estado: Mapped[EstadoExportacion] = enum_col(EstadoExportacion, default=EstadoExportacion.SOLICITADA)
    plan_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)
    estudiante_id: Mapped[int | None] = fk("estudiante.id", nullable=True)
    parametros: Mapped[JS | None]
    archivo_key: Mapped[S500 | None]
    archivo_nombre: Mapped[S255 | None]
    content_type: Mapped[S100 | None]
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[S1000 | None]
    completada_at: Mapped[DT | None]
    expira_at: Mapped[DT | None]


# ----------------------------------------------------------------------------- auditoria
class LogAuditoria(IdMixin, Base):
    """Registro de auditoria de SOLO ANEXO (RF-38). Sin updated_at ni soft delete.

    Proteccion ORM: update/delete de instancias y bulk UPDATE/DELETE lanzan `AuditoriaInmutableError`.
    Proteccion de BD: en PostgreSQL la migracion inicial crea un trigger que rechaza UPDATE/DELETE.
    `actor_id` no lleva FK para que el registro sobreviva a la baja de usuarios.
    """

    __tablename__ = "log_auditoria"
    __table_args__ = (
        Index("ix_log_auditoria_entidad", "entidad", "entidad_id"),
        Index("ix_log_auditoria_actor_fecha", "actor_id", "created_at"),
        Index("ix_log_auditoria_estudiante", "estudiante_id", "created_at"),
    )

    created_at: Mapped[DT] = mapped_column(UTCDateTime(), default=utcnow, nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_rol: Mapped[S20 | None]
    accion: Mapped[S100] = mapped_column(index=True)
    entidad: Mapped[S100 | None]
    entidad_id: Mapped[int | None] = mapped_column(Integer)
    estudiante_id: Mapped[int | None] = mapped_column(Integer)  # estudiante afectado (para auditar accesos sensibles)
    detalle: Mapped[JS | None]
    ip: Mapped[S50 | None]
    user_agent: Mapped[S255 | None]
    request_id: Mapped[S50 | None]


class AuditoriaInmutableError(RuntimeError):
    """Se intento modificar o borrar un registro de auditoria."""


@event.listens_for(LogAuditoria, "before_update")
def _log_no_update(mapper, connection, target):
    raise AuditoriaInmutableError("LOG_AUDITORIA es de solo anexo: no se puede modificar.")


@event.listens_for(LogAuditoria, "before_delete")
def _log_no_delete(mapper, connection, target):
    raise AuditoriaInmutableError("LOG_AUDITORIA es de solo anexo: no se puede eliminar.")


@event.listens_for(Session, "do_orm_execute")
def _log_no_bulk(state):
    if state.is_update or state.is_delete:
        stmt = state.statement
        table = getattr(stmt, "table", None)
        if table is not None and getattr(table, "name", None) == LogAuditoria.__tablename__:
            raise AuditoriaInmutableError("LOG_AUDITORIA es de solo anexo: no se permiten UPDATE/DELETE masivos.")
