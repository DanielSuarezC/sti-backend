"""slice A: fecha de inicio de practicas en el calendario academico

Revision ID: 00A1
Revises: 0001
Create Date: 2026-11-16 22:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '00A1'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calendario_academico', sa.Column('fecha_inicio_practicas', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('calendario_academico') as batch:
        batch.drop_column('fecha_inicio_practicas')
