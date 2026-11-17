"""Schemas del tablero de estudiantes y de "Mi ruta".

# OWNER: slice C2
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AsignarBienestar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bienestar_usuario_id: int | None = None  # null = dejar sin asignar
