"""slice B: consentimiento_detalle, solicitud_arco, barrera_facilitador, historia_academica, meta_estudiante,
formato_comentario, perfil_fortalezas_estado

Revision ID: 00B1
Revises: 0001
Create Date: 2026-11-16 22:00:00

Solo crea tablas NUEVAS (ningun cambio a tablas existentes). Ver app/models/slice_b.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00B1"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('formato_comentario',
    sa.Column('estudiante_id', sa.Integer(), nullable=False),
    sa.Column('formato', sa.String(length=20), nullable=False),
    sa.Column('seccion', sa.String(length=50), nullable=False),
    sa.Column('autor_id', sa.Integer(), nullable=False),
    sa.Column('autor_rol', sa.String(length=20), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['autor_id'], ['usuario.id'], ),
    sa.ForeignKeyConstraint(['estudiante_id'], ['estudiante.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('solicitud_arco',
    sa.Column('estudiante_id', sa.Integer(), nullable=False),
    sa.Column('solicitante_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.Enum('ACCESO', 'RECTIFICACION', 'CANCELACION', 'OPOSICION', name='ck_solicitud_arco_tipo', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('estado', sa.Enum('RECIBIDA', 'EN_TRAMITE', 'RESUELTA', 'RECHAZADA', name='ck_solicitud_arco_estado', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('fecha_limite', sa.Date(), nullable=False),
    sa.Column('prorrogada', sa.Boolean(), nullable=False),
    sa.Column('motivo_prorroga', sa.String(length=500), nullable=True),
    sa.Column('respuesta', sa.Text(), nullable=True),
    sa.Column('atendida_por_id', sa.Integer(), nullable=True),
    sa.Column('atendida_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['atendida_por_id'], ['usuario.id'], ),
    sa.ForeignKeyConstraint(['estudiante_id'], ['estudiante.id'], ),
    sa.ForeignKeyConstraint(['solicitante_id'], ['usuario.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('barrera_facilitador',
    sa.Column('barrera_id', sa.Integer(), nullable=False),
    sa.Column('facilitador_id', sa.Integer(), nullable=False),
    sa.Column('nota', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['barrera_id'], ['barrera_identificada.id'], ),
    sa.ForeignKeyConstraint(['facilitador_id'], ['facilitador.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('consentimiento_detalle',
    sa.Column('consentimiento_id', sa.Integer(), nullable=False),
    sa.Column('nombre_firmante', sa.String(length=255), nullable=False),
    sa.Column('modalidad', sa.Enum('AUTONOMA', 'ASISTIDA_BIENESTAR', name='ck_consentimiento_detalle_modalidad', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('asistido_por_id', sa.Integer(), nullable=True),
    sa.Column('acepta_compartir_ajustes_docentes', sa.Boolean(), nullable=False),
    sa.Column('copia_enviada_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['asistido_por_id'], ['usuario.id'], ),
    sa.ForeignKeyConstraint(['consentimiento_id'], ['consentimiento.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('historia_academica',
    sa.Column('caracterizacion_id', sa.Integer(), nullable=False),
    sa.Column('trayectoria_escolar', sa.Text(), nullable=True),
    sa.Column('apoyos_previos', sa.Text(), nullable=True),
    sa.Column('experiencias_exitosas', sa.Text(), nullable=True),
    sa.Column('dificultades_previas', sa.Text(), nullable=True),
    sa.Column('otras_observaciones', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['caracterizacion_id'], ['caracterizacion.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('meta_estudiante',
    sa.Column('perfil_fortalezas_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.Enum('ACADEMICA', 'PROFESIONAL', 'PERSONAL', name='ck_meta_estudiante_tipo', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('plazo', sa.String(length=50), nullable=True),
    sa.Column('prioridad', sa.Enum('BAJA', 'MEDIA', 'ALTA', name='ck_meta_estudiante_prioridad', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['perfil_fortalezas_id'], ['perfil_fortalezas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('perfil_fortalezas_estado',
    sa.Column('perfil_fortalezas_id', sa.Integer(), nullable=False),
    sa.Column('estado', sa.Enum('COMPLETA', 'INCOMPLETA', 'EN_REVISION', name='ck_perfil_fortalezas_estado_estado', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('confirmado_por_id', sa.Integer(), nullable=True),
    sa.Column('confirmado_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_reason', sa.String(length=500), nullable=True),
    sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['confirmado_por_id'], ['usuario.id'], ),
    sa.ForeignKeyConstraint(['perfil_fortalezas_id'], ['perfil_fortalezas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consentimiento_detalle_asistido_por_id'), 'consentimiento_detalle', ['asistido_por_id'], unique=False)
    op.create_index(op.f('ix_consentimiento_detalle_consentimiento_id'), 'consentimiento_detalle', ['consentimiento_id'], unique=True)
    op.create_index(op.f('ix_consentimiento_detalle_deleted_at'), 'consentimiento_detalle', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_solicitud_arco_atendida_por_id'), 'solicitud_arco', ['atendida_por_id'], unique=False)
    op.create_index(op.f('ix_solicitud_arco_deleted_at'), 'solicitud_arco', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_solicitud_arco_estudiante_id'), 'solicitud_arco', ['estudiante_id'], unique=False)
    op.create_index(op.f('ix_solicitud_arco_solicitante_id'), 'solicitud_arco', ['solicitante_id'], unique=False)
    op.create_index(op.f('ix_barrera_facilitador_barrera_id'), 'barrera_facilitador', ['barrera_id'], unique=False)
    op.create_index(op.f('ix_barrera_facilitador_deleted_at'), 'barrera_facilitador', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_barrera_facilitador_facilitador_id'), 'barrera_facilitador', ['facilitador_id'], unique=False)
    op.create_index('uq_barrera_facilitador', 'barrera_facilitador', ['barrera_id', 'facilitador_id'], unique=True, sqlite_where=sa.text('deleted_at IS NULL'), postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_historia_academica_caracterizacion_id'), 'historia_academica', ['caracterizacion_id'], unique=False)
    op.create_index(op.f('ix_historia_academica_deleted_at'), 'historia_academica', ['deleted_at'], unique=False)
    op.create_index('uq_historia_academica_caract', 'historia_academica', ['caracterizacion_id'], unique=True, sqlite_where=sa.text('deleted_at IS NULL'), postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_meta_estudiante_deleted_at'), 'meta_estudiante', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_meta_estudiante_perfil_fortalezas_id'), 'meta_estudiante', ['perfil_fortalezas_id'], unique=False)
    op.create_index(op.f('ix_formato_comentario_autor_id'), 'formato_comentario', ['autor_id'], unique=False)
    op.create_index(op.f('ix_formato_comentario_deleted_at'), 'formato_comentario', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_formato_comentario_estudiante_id'), 'formato_comentario', ['estudiante_id'], unique=False)
    op.create_index(op.f('ix_perfil_fortalezas_estado_confirmado_por_id'), 'perfil_fortalezas_estado', ['confirmado_por_id'], unique=False)
    op.create_index(op.f('ix_perfil_fortalezas_estado_deleted_at'), 'perfil_fortalezas_estado', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_perfil_fortalezas_estado_perfil_fortalezas_id'), 'perfil_fortalezas_estado', ['perfil_fortalezas_id'], unique=False)
    op.create_index('uq_perfil_fortalezas_estado', 'perfil_fortalezas_estado', ['perfil_fortalezas_id'], unique=True, sqlite_where=sa.text('deleted_at IS NULL'), postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_perfil_fortalezas_estado', table_name='perfil_fortalezas_estado')
    op.drop_index(op.f('ix_perfil_fortalezas_estado_perfil_fortalezas_id'), table_name='perfil_fortalezas_estado')
    op.drop_index(op.f('ix_perfil_fortalezas_estado_deleted_at'), table_name='perfil_fortalezas_estado')
    op.drop_index(op.f('ix_perfil_fortalezas_estado_confirmado_por_id'), table_name='perfil_fortalezas_estado')
    op.drop_index(op.f('ix_formato_comentario_estudiante_id'), table_name='formato_comentario')
    op.drop_index(op.f('ix_formato_comentario_deleted_at'), table_name='formato_comentario')
    op.drop_index(op.f('ix_formato_comentario_autor_id'), table_name='formato_comentario')
    op.drop_index(op.f('ix_meta_estudiante_perfil_fortalezas_id'), table_name='meta_estudiante')
    op.drop_index(op.f('ix_meta_estudiante_deleted_at'), table_name='meta_estudiante')
    op.drop_index('uq_historia_academica_caract', table_name='historia_academica')
    op.drop_index(op.f('ix_historia_academica_deleted_at'), table_name='historia_academica')
    op.drop_index(op.f('ix_historia_academica_caracterizacion_id'), table_name='historia_academica')
    op.drop_index('uq_barrera_facilitador', table_name='barrera_facilitador')
    op.drop_index(op.f('ix_barrera_facilitador_facilitador_id'), table_name='barrera_facilitador')
    op.drop_index(op.f('ix_barrera_facilitador_deleted_at'), table_name='barrera_facilitador')
    op.drop_index(op.f('ix_barrera_facilitador_barrera_id'), table_name='barrera_facilitador')
    op.drop_index(op.f('ix_solicitud_arco_solicitante_id'), table_name='solicitud_arco')
    op.drop_index(op.f('ix_solicitud_arco_estudiante_id'), table_name='solicitud_arco')
    op.drop_index(op.f('ix_solicitud_arco_deleted_at'), table_name='solicitud_arco')
    op.drop_index(op.f('ix_solicitud_arco_atendida_por_id'), table_name='solicitud_arco')
    op.drop_index(op.f('ix_consentimiento_detalle_deleted_at'), table_name='consentimiento_detalle')
    op.drop_index(op.f('ix_consentimiento_detalle_consentimiento_id'), table_name='consentimiento_detalle')
    op.drop_index(op.f('ix_consentimiento_detalle_asistido_por_id'), table_name='consentimiento_detalle')
    op.drop_table('perfil_fortalezas_estado')
    op.drop_table('meta_estudiante')
    op.drop_table('historia_academica')
    op.drop_table('consentimiento_detalle')
    op.drop_table('barrera_facilitador')
    op.drop_table('solicitud_arco')
    op.drop_table('formato_comentario')
