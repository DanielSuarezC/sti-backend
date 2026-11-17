"""slice C1: columnas aditivas del Plan MAAR-TEA (concertacion, participacion) y de la matriz F7

Revision ID: 00C1
Revises: 0001
Create Date: 2026-11-16 21:00:00

Solo agrega columnas NULLABLE (sin FK, sin CHECK) a plan_maar_tea, estrategia_dua, ajuste_razonable y apoyo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "00C1"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_COLUMNS: dict[str, list[sa.Column]] = {
    "plan_maar_tea": [
        sa.Column("comentarios_validacion", sa.Text(), nullable=True),
        sa.Column("enviado_a_estudiante_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("participacion_log", _JSON, nullable=True),
    ],
    "estrategia_dua": [
        sa.Column("barrera_id", sa.Integer(), nullable=True),
        sa.Column("fortaleza_id", sa.Integer(), nullable=True),
        sa.Column("origen", sa.String(length=30), nullable=True),
        sa.Column("propuesta_por_id", sa.Integer(), nullable=True),
        sa.Column("propuesta_por_rol", sa.String(length=20), nullable=True),
        sa.Column("modificado_por_id", sa.Integer(), nullable=True),
        sa.Column("modificado_at", sa.DateTime(timezone=True), nullable=True),
    ],
    "ajuste_razonable": [
        sa.Column("recurso", sa.String(length=500), nullable=True),
        sa.Column("origen", sa.String(length=30), nullable=True),
        sa.Column("propuesto_por_id", sa.Integer(), nullable=True),
        sa.Column("propuesto_por_rol", sa.String(length=20), nullable=True),
        sa.Column("modificado_por_id", sa.Integer(), nullable=True),
        sa.Column("modificado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("respuesta_estudiante", sa.String(length=30), nullable=True),
        sa.Column("comentario_estudiante", sa.Text(), nullable=True),
        sa.Column("modificacion_propuesta", sa.Text(), nullable=True),
        sa.Column("comentario_responsable", sa.Text(), nullable=True),
    ],
    "apoyo": [
        sa.Column("estrategia_id", sa.Integer(), nullable=True),
        sa.Column("calendario_id", sa.Integer(), nullable=True),
    ],
}


def upgrade() -> None:
    for table, cols in _COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for col in cols:
                batch.add_column(col)


def downgrade() -> None:
    for table, cols in _COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for col in reversed(cols):
                batch.drop_column(col.name)
