"""Mensajería auxiliar del slice A para eventos que no están en el catálogo de `notifications.py`.

* `queue_email`: correo directo a una dirección (p. ej. solicitante sin cuenta) vía EMAIL_OUTBOX.
* `push`: notificación in-app con tipo/título/mensaje propios (idempotente por `dedupe_key`).
Ambas respetan la degradación sin SMTP (correo OMITIDO + log). No hacen commit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import EstadoEmail
from app.models.sistema import EmailOutbox, Notificacion
from app.services import email as email_service
from app.services import notifications


def queue_email(
    db: Session, *, to_email: str, asunto: str, cuerpo: str, evento: str, usuario_id: int | None = None,
    dedupe_key: str | None = None,
) -> EmailOutbox | None:
    if dedupe_key and db.scalar(select(EmailOutbox.id).where(EmailOutbox.dedupe_key == dedupe_key).limit(1)):
        return None
    row = EmailOutbox(
        usuario_id=usuario_id, destinatario_email=to_email, asunto=asunto[:255], cuerpo_texto=cuerpo, evento=evento,
        estado=EstadoEmail.PENDIENTE, dedupe_key=dedupe_key,
    )
    db.add(row)
    db.flush()
    if get_settings().smtp_configured:
        notifications._schedule_after_commit(db)
    else:
        email_service.deliver(row)
        db.flush()
    return row


def push(
    db: Session, usuario_ids: list[int], *, tipo: str, titulo: str, mensaje: str, enlace: str | None = None,
    dedupe_key: str | None = None, payload: dict[str, Any] | None = None,
) -> int:
    """Crea una notificación in-app por usuario. Devuelve cuántas creó (omite las ya existentes por dedupe)."""
    creadas = 0
    for uid in dict.fromkeys(usuario_ids):
        key = f"{dedupe_key}:u{uid}" if dedupe_key else None
        if key and db.scalar(select(Notificacion.id).where(Notificacion.dedupe_key == key).limit(1)):
            continue
        db.add(Notificacion(usuario_id=uid, tipo=tipo, titulo=titulo[:255], mensaje=mensaje, enlace=enlace,
                            payload=payload, dedupe_key=key))
        creadas += 1
    db.flush()
    return creadas
