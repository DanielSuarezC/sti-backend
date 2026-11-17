"""slice C3: F10 (cierre de semestre / continuidad), panel del Docente y Familiar Autorizado

Revision ID: 00C3
Revises: 0001
Create Date: 2026-11-16 22:00:00

Cambios (solo aditivos):
* tabla nueva `f10_semestre`: cabecera del F10 por estudiante y semestre (decisiones del plan, proyeccion, necesidades
  anticipadas, doble aprobacion con sello de tiempo, plan del siguiente semestre generado).
* `AlcanceFamiliar.NOTIFICACIONES` es un valor nuevo dentro de una lista JSON (`autorizacion_familiar.alcance`): no hay
  cambio de esquema.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "00C3"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "f10_semestre",
        sa.Column("estudiante_id", sa.Integer(), nullable=False),
        sa.Column("semestre_origen", sa.String(length=20), nullable=False),
        sa.Column("semestre_destino", sa.String(length=20), nullable=False),
        sa.Column(
            "estado",
            sa.Enum("BORRADOR", "PENDIENTE_APROBACION", "APROBADO", name="ck_f10_semestre_estado",
                    native_enum=False, create_constraint=True, length=40),
            nullable=False,
        ),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("evaluacion_id", sa.Integer(), nullable=True),
        sa.Column("trayectoria_id", sa.Integer(), nullable=True),
        sa.Column("plan_siguiente_id", sa.Integer(), nullable=True),
        sa.Column("actualizacion_plan", _JSON, nullable=False),
        sa.Column("necesidades_anticipadas", _JSON, nullable=False),
        sa.Column("proyeccion", _JSON, nullable=True),
        sa.Column("generado_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elaborado_por_id", sa.Integer(), nullable=True),
        sa.Column("aprobado_bienestar_por_id", sa.Integer(), nullable=True),
        sa.Column("aprobado_bienestar_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aprobado_estudiante_por_id", sa.Integer(), nullable=True),
        sa.Column("aprobado_estudiante_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comentario_estudiante", sa.Text(), nullable=True),
        sa.Column("aprobado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_reason", sa.String(length=500), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["aprobado_bienestar_por_id"], ["usuario.id"]),
        sa.ForeignKeyConstraint(["aprobado_estudiante_por_id"], ["usuario.id"]),
        sa.ForeignKeyConstraint(["elaborado_por_id"], ["usuario.id"]),
        sa.ForeignKeyConstraint(["estudiante_id"], ["estudiante.id"]),
        sa.ForeignKeyConstraint(["evaluacion_id"], ["evaluacion_plan.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plan_maar_tea.id"]),
        sa.ForeignKeyConstraint(["plan_siguiente_id"], ["plan_maar_tea.id"]),
        sa.ForeignKeyConstraint(["trayectoria_id"], ["trayectoria_academica.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("aprobado_bienestar_por_id", "aprobado_estudiante_por_id", "deleted_at", "elaborado_por_id",
                "estudiante_id", "evaluacion_id", "plan_id", "plan_siguiente_id", "trayectoria_id"):
        op.create_index(op.f(f"ix_f10_semestre_{col}"), "f10_semestre", [col], unique=False)
    op.create_index(
        "uq_f10_estudiante_semestre_origen", "f10_semestre", ["estudiante_id", "semestre_origen"], unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"), postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_f10_estudiante_semestre_origen", table_name="f10_semestre",
                  sqlite_where=sa.text("deleted_at IS NULL"), postgresql_where=sa.text("deleted_at IS NULL"))
    for col in ("trayectoria_id", "plan_siguiente_id", "plan_id", "evaluacion_id", "estudiante_id", "elaborado_por_id",
                "deleted_at", "aprobado_estudiante_por_id", "aprobado_bienestar_por_id"):
        op.drop_index(op.f(f"ix_f10_semestre_{col}"), table_name="f10_semestre")
    op.drop_table("f10_semestre")
