"""Schemas de notificaciones (contrato con el frontend)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NotificacionOut(BaseModel):
    id: int
    tipo: str
    titulo: str
    mensaje: str
    leida: bool
    created_at: datetime
    enlace: str | None = None


class NotificacionesResponse(BaseModel):
    items: list[NotificacionOut]
    total: int
    no_leidas: int
    page: int
    page_size: int
