"""F8 - Seguimiento semestral (semaforo): SEGUIMIENTO, REGISTRO_SEGUIMIENTO, EVIDENCIA_EFECTIVIDAD,
RESULTADO_INDICADOR (ERD §3.47-3.50) + REGISTRO_SEGUIMIENTO_AJUSTE (semaforo y percepcion por ajuste y corte).

`documento_adjunto` (LONGBLOB) -> referencia a almacenamiento (`archivo_*`).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    DEC,
    DT,
    JS,
    JSL,
    S20,
    S100,
    S255,
    S500,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
    unique_active,
)
from app.models.enums import (
    Corte,
    DimensionResultado,
    PercepcionEstudiante,
    Semaforo,
    TipoEvidenciaEfectividad,
    TipoRegistroSeguimiento,
)


class Seguimiento(Entity, Base):
    __tablename__ = "seguimiento"
    __table_args__ = (
        Index("idx_seguimiento_plan_fecha", "plan_id", "fecha_seguimiento"),
        unique_active("uq_seguimiento_plan_corte", "plan_id", "corte"),
    )

    estudiante_id: Mapped[int] = fk("estudiante.id")
    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    corte: Mapped[Corte] = enum_col(Corte)  # C1 / C2 / C3
    semestre_academico: Mapped[S20 | None]
    calendario_id: Mapped[int | None] = fk("calendario_academico.id", nullable=True)
    fecha_seguimiento: Mapped[date]
    profesional_responsable_id: Mapped[int] = fk("usuario.id")
    participantes_ids: Mapped[JSL | None]  # ERD: VARCHAR(500) -> lista JSON
    descripcion_situacion_actual: Mapped[TXT | None]
    funcionamiento_apoyos: Mapped[TXT | None]
    dificultades_emergentes: Mapped[TXT | None]
    ajustes_recomendados: Mapped[TXT | None]
    semaforo_estado: Mapped[Semaforo | None] = enum_col(Semaforo, nullable=True)  # peor semaforo de los ajustes
    version_plan: Mapped[int | None] = mapped_column(Integer)
    fecha_proximo_seguimiento: Mapped[date | None]
    observaciones_generales: Mapped[TXT | None]
    cerrado: Mapped[bool] = mapped_column(default=False)
    # Slice C2 (aditivo): barreras emergentes registradas en este corte [{barrera_id, tipo_barrera, ajuste_id, propuesta_ajuste, ...}]
    barreras_emergentes: Mapped[JSL | None]

    registros: Mapped[list[RegistroSeguimiento]] = relationship(back_populates="seguimiento")
    evidencias: Mapped[list[EvidenciaEfectividad]] = relationship(back_populates="seguimiento")
    registros_ajuste: Mapped[list[RegistroSeguimientoAjuste]] = relationship(back_populates="seguimiento")


class RegistroSeguimiento(Entity, Base):
    __tablename__ = "registro_seguimiento"

    seguimiento_id: Mapped[int] = fk("seguimiento.id")
    tipo_registro: Mapped[TipoRegistroSeguimiento] = enum_col(TipoRegistroSeguimiento)
    descripcion_metodologia: Mapped[TXT | None]
    fuentes_informacion: Mapped[S500 | None]
    archivo_key: Mapped[S500 | None]
    archivo_nombre: Mapped[S255 | None]
    archivo_content_type: Mapped[S100 | None]
    archivo_size: Mapped[int | None] = mapped_column(Integer)

    seguimiento: Mapped[Seguimiento] = relationship(back_populates="registros")


class EvidenciaEfectividad(Entity, Base):
    __tablename__ = "evidencia_efectividad"

    seguimiento_id: Mapped[int] = fk("seguimiento.id")
    tipo_evidencia: Mapped[TipoEvidenciaEfectividad] = enum_col(TipoEvidenciaEfectividad)
    descripcion_evidencia: Mapped[TXT]
    fuente_evidencia: Mapped[S255 | None]
    dato_cuantitativo: Mapped[DEC | None]
    periodo_medicion: Mapped[S100 | None]

    seguimiento: Mapped[Seguimiento] = relationship(back_populates="evidencias")
    resultados: Mapped[list[ResultadoIndicador]] = relationship(back_populates="evidencia")


class ResultadoIndicador(Entity, Base):
    __tablename__ = "resultado_indicador"
    __table_args__ = (
        CheckConstraint("porcentaje_cumplimiento IS NULL OR (porcentaje_cumplimiento >= 0 AND porcentaje_cumplimiento <= 100)",
                        name="ck_resultado_indicador_porcentaje"),
    )

    evidencia_id: Mapped[int] = fk("evidencia_efectividad.id")
    dimension_resultado: Mapped[DimensionResultado] = enum_col(DimensionResultado)  # ERD: dimensión_resultado
    indicador_especifico: Mapped[TXT]
    valor_logrado: Mapped[TXT | None]  # ERD: "TEXT o DECIMAL" -> texto
    meta_establecida: Mapped[TXT | None]
    porcentaje_cumplimiento: Mapped[int | None] = mapped_column(Integer)
    interpretacion: Mapped[TXT | None]

    evidencia: Mapped[EvidenciaEfectividad] = relationship(back_populates="resultados")


class RegistroSeguimientoAjuste(Entity, Base):
    """Semaforo + percepcion por ajuste y por corte (v7 M6). Un Rojo dispara RF-39 (servicio)."""

    __tablename__ = "registro_seguimiento_ajuste"
    __table_args__ = (unique_active("uq_regseg_ajuste_seguimiento", "seguimiento_id", "ajuste_id"),)

    seguimiento_id: Mapped[int] = fk("seguimiento.id")
    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    corte: Mapped[Corte] = enum_col(Corte)
    # Slice C2: nullable. La fila puede nacer por la percepcion del estudiante (HU-21) antes de que Bienestar valore.
    semaforo: Mapped[Semaforo | None] = enum_col(Semaforo, nullable=True)
    implementado: Mapped[bool | None]
    frecuencia_implementacion: Mapped[S255 | None]
    resultado_observado: Mapped[TXT | None]
    percepcion_estudiante: Mapped[PercepcionEstudiante | None] = enum_col(PercepcionEstudiante, nullable=True)
    comentario_estudiante: Mapped[TXT | None]
    comentario_docente: Mapped[TXT | None]
    nueva_barrera_detectada: Mapped[TXT | None]  # barrera emergente (v7 M6)
    registrado_por_id: Mapped[int] = fk("usuario.id")
    rol_registrante: Mapped[S20 | None]
    semaforo_cambiado_at: Mapped[DT | None]
    # Slice C2 (aditivo): tarea de concertacion (AMARILLO, RF-29) y rediseno registrado (ROJO, RF-39). Ver services/semaforo.py
    tarea_concertacion: Mapped[JS | None]
    rediseno: Mapped[JS | None]

    seguimiento: Mapped[Seguimiento] = relationship(back_populates="registros_ajuste")
