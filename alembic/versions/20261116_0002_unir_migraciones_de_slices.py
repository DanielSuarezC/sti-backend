"""unir migraciones de slices

Revision ID: 0002
Revises: 00A1, 00B1, 00C1, 00C2, 00C3
Create Date: 2026-11-16 21:56:30.863552
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = ('00A1', '00B1', '00C1', '00C2', '00C3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
