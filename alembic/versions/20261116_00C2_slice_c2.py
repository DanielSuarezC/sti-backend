"""slice C2: seguimiento F8 (semaforo, tarea de concertacion, rediseno) y evaluacion F9 (estado, sintesis, 9 dimensiones)

Revision ID: 00C2
Revises: 0001
Create Date: 2026-11-16 21:30:00

Cambios (todos aditivos salvo uno):
* registro_seguimiento_ajuste: `semaforo` pasa a NULLABLE (la fila puede nacer por la percepcion del estudiante, HU-21,
  antes de que Bienestar valore); + `tarea_concertacion` JSON y `rediseno` JSON.
* seguimiento: + `barreras_emergentes` JSON (lista de barreras emergentes registradas en el corte).
* evaluacion_plan: + `estado` (BORRADOR/CERRADA, server_default BORRADOR), `cerrada_at`, `sintesis` JSON, `valoracion_dimensiones` JSON.
* decision_plan: + `lecciones_aprendidas` TEXT.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "00C2"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
_SEMAFORO = sa.Enum(
    "VERDE", "AMARILLO", "ROJO", name="ck_registro_seguimiento_ajuste_semaforo", native_enum=False,
    create_constraint=True, length=40,
)


def upgrade() -> None:
    with op.batch_alter_table("registro_seguimiento_ajuste") as batch:
        batch.alter_column("semaforo", existing_type=_SEMAFORO, nullable=True)
        batch.add_column(sa.Column("tarea_concertacion", _JSON, nullable=True))
        batch.add_column(sa.Column("rediseno", _JSON, nullable=True))
    with op.batch_alter_table("seguimiento") as batch:
        batch.add_column(sa.Column("barreras_emergentes", _JSON, nullable=True))
    with op.batch_alter_table("evaluacion_plan") as batch:
        batch.add_column(sa.Column("estado", sa.String(length=20), nullable=False, server_default="BORRADOR"))
        batch.add_column(sa.Column("cerrada_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("sintesis", _JSON, nullable=True))
        batch.add_column(sa.Column("valoracion_dimensiones", _JSON, nullable=True))
    with op.batch_alter_table("decision_plan") as batch:
        batch.add_column(sa.Column("lecciones_aprendidas", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("decision_plan") as batch:
        batch.drop_column("lecciones_aprendidas")
    with op.batch_alter_table("seguimiento") as batch:
        batch.drop_column("barreras_emergentes")
    with op.batch_alter_table("evaluacion_plan") as batch:
        for col in ("valoracion_dimensiones", "sintesis", "cerrada_at", "estado"):
            batch.drop_column(col)
    with op.batch_alter_table("registro_seguimiento_ajuste") as batch:
        batch.drop_column("rediseno")
        batch.drop_column("tarea_concertacion")
        batch.alter_column("semaforo", existing_type=_SEMAFORO, nullable=False)
