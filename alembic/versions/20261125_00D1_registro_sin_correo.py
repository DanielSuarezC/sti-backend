"""registro autónomo sin correo: código de recuperación y código de vinculación de familiares

Revision ID: 00D1
Revises: 0002
Create Date: 2026-11-25 10:00:00

Cambios (solo aditivos, columnas nulas):
* `usuario.recovery_code_hash`: hash del código de recuperación de contraseña (se muestra una sola vez).
* `autorizacion_familiar.codigo_vinculacion`: código que el estudiante entrega al familiar para que se registre.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00D1"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuario", sa.Column("recovery_code_hash", sa.String(length=100), nullable=True))
    op.add_column("autorizacion_familiar", sa.Column("codigo_vinculacion", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("autorizacion_familiar", "codigo_vinculacion")
    op.drop_column("usuario", "recovery_code_hash")
