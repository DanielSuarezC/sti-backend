"""Utilidades compartidas por las pruebas del slice A."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select

from app.models import EmailOutbox
from app.models.academico import CalendarioAcademico
from app.services.directorio import reset_directory_settings


def token_from_outbox(db, email: str) -> str:
    """Último token de activación enviado a `email` (se lee del cuerpo del correo en la cola)."""
    db.expire_all()
    rows = db.scalars(select(EmailOutbox).where(EmailOutbox.destinatario_email == email).order_by(EmailOutbox.id)).all()
    assert rows, f"no hay correos para {email}"
    m = re.search(r"token=([A-Za-z0-9_\-]+)", rows[-1].cuerpo_texto)
    assert m, rows[-1].cuerpo_texto
    return m.group(1)


def set_domains(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("INSTITUTIONAL_EMAIL_DOMAINS", raising=False)
    else:
        monkeypatch.setenv("INSTITUTIONAL_EMAIL_DOMAINS", value)
    reset_directory_settings()


def make_calendar(db, *, hoy: date, programa_id=None, offset_inicio: int = -30, activo: bool = True, **kw) -> CalendarioAcademico:
    from datetime import timedelta

    inicio = hoy + timedelta(days=offset_inicio)
    c = CalendarioAcademico(
        semestre_academico=kw.pop("semestre", "2026-II"), programa_id=programa_id, fecha_inicio=inicio,
        fecha_fin=inicio + timedelta(weeks=17), fecha_c1=kw.pop("c1", inicio + timedelta(weeks=6, days=2)),
        fecha_c2=kw.pop("c2", inicio + timedelta(weeks=11, days=2)), fecha_c3=kw.pop("c3", inicio + timedelta(weeks=16, days=2)),
        activo=activo, **kw,
    )
    db.add(c)
    db.commit()
    return c
