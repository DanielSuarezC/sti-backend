"""Envío de correo por SMTP y procesamiento de la cola EMAIL_OUTBOX.

Sin `SMTP_HOST` no se envía nada: los correos quedan en EMAIL_OUTBOX con estado OMITIDO y se registran en logs
(útil en desarrollo: el enlace de activación se puede copiar del log).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.base import utcnow
from app.models.enums import EstadoEmail
from app.models.sistema import EmailOutbox

logger = logging.getLogger("sti.email")

MAX_INTENTOS = 5


def smtp_send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Envía un correo real. Lanza excepción si falla (el llamador decide el reintento)."""
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if s.smtp_ssl:
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ssl.create_default_context(), timeout=20) as srv:
            if s.smtp_user:
                srv.login(s.smtp_user, s.smtp_password)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as srv:
            if s.smtp_starttls:
                srv.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                srv.login(s.smtp_user, s.smtp_password)
            srv.send_message(msg)


def deliver(row: EmailOutbox) -> None:
    """Intenta enviar una fila de outbox y actualiza su estado (no hace commit)."""
    s = get_settings()
    if not s.smtp_configured:
        row.estado = EstadoEmail.OMITIDO
        logger.info("[EMAIL OMITIDO - sin SMTP] to=%s asunto=%s\n%s", row.destinatario_email, row.asunto, row.cuerpo_texto)
        return
    row.intentos = (row.intentos or 0) + 1
    try:
        smtp_send(row.destinatario_email, row.asunto, row.cuerpo_texto, row.cuerpo_html)
        row.estado = EstadoEmail.ENVIADO
        row.enviado_at = utcnow()
        row.ultimo_error = None
    except Exception as exc:  # noqa: BLE001 - cualquier fallo SMTP se registra
        row.estado = EstadoEmail.ERROR if row.intentos >= MAX_INTENTOS else EstadoEmail.PENDIENTE
        row.ultimo_error = str(exc)[:900]
        logger.warning("Fallo SMTP (intento %s) a %s: %s", row.intentos, row.destinatario_email, exc)


def process_outbox(db: Session, limit: int = 100) -> int:
    """Envía los correos PENDIENTES. Devuelve cuántos se procesaron. Hace commit."""
    rows = db.scalars(
        select(EmailOutbox).where(EmailOutbox.estado == EstadoEmail.PENDIENTE).order_by(EmailOutbox.id).limit(limit)
    ).all()
    for row in rows:
        deliver(row)
    db.commit()
    return len(rows)
