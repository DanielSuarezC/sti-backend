"""Schemas de exportación (RF-27). Respuestas documentadas en docs/api/slice_c1.md."""

from __future__ import annotations

from enum import StrEnum


class FormatoExportacion(StrEnum):
    pdf = "pdf"
    docx = "docx"
    html = "html"  # alternativa imprimible cuando el servidor no puede generar PDF
