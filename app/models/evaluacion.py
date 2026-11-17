"""F9 - Evaluacion de efectividad (EVALUACION_PLAN, DECISION_PLAN) y F10 - NOTA_CONTINUIDAD (ERD §3.51-3.52 + v7 §7.3).

NOTA_CONTINUIDAD: texto CIFRADO; requiere aprobacion explicita del estudiante antes de quedar disponible (RF-35).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    CTXT,
    DT,
    JS,
    S20,
    S100,
    TXT,
    Base,
    Entity,
    enum_col,
    fk,
)
from app.models.enums import (
    DestinatarioNota,
    ElementoAfectado,
    EstadoDecision,
    EstadoNotaContinuidad,
    NivelBMA,
    TipoDecision,
)


class EvaluacionPlan(Entity, Base):
    __tablename__ = "evaluacion_plan"

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    fecha_evaluacion: Mapped[date]
    evaluador_id: Mapped[int] = fk("usuario.id")
    periodo_evaluacion: Mapped[S100 | None]
    evidencias_resumidas: Mapped[TXT | None]
    efectividad_general: Mapped[NivelBMA] = enum_col(NivelBMA, default=NivelBMA.MEDIA)
    apoyos_efectivos: Mapped[TXT | None]
    apoyos_requieren_ajuste: Mapped[TXT | None]
    apoyos_a_discontinuar: Mapped[TXT | None]
    nuevas_barreras_identificadas: Mapped[TXT | None]
    fortalezas_emergentes: Mapped[TXT | None]
    cambios_contexto: Mapped[TXT | None]
    recomendaciones: Mapped[TXT | None]
    lecciones_aprendidas: Mapped[TXT | None]  # v7 M7
    alimento_cbr: Mapped[bool] = mapped_column(default=False)  # ya registro casos exitosos en el motor CBR
    # Slice C2 (aditivo): ciclo de vida del F9 (BORRADOR -> CERRADA), sintesis automatica y valoracion de las 9 dimensiones
    estado: Mapped[S20] = mapped_column(default="BORRADOR", server_default="BORRADOR")
    cerrada_at: Mapped[DT | None]
    sintesis: Mapped[JS | None]
    valoracion_dimensiones: Mapped[JS | None]  # {"ACCESO": {"nivel": "ALTA", "comentario": "..."}, ...}

    decisiones: Mapped[list[DecisionPlan]] = relationship(back_populates="evaluacion")


class DecisionPlan(Entity, Base):
    __tablename__ = "decision_plan"

    evaluacion_id: Mapped[int] = fk("evaluacion_plan.id")
    tipo_decision: Mapped[TipoDecision] = enum_col(TipoDecision)
    elemento_afectado: Mapped[ElementoAfectado] = enum_col(ElementoAfectado)
    elemento_id: Mapped[int | None] = mapped_column(Integer)  # id polimorfico (segun elemento_afectado)
    descripcion_decision: Mapped[TXT]
    justificacion_decision: Mapped[TXT | None]
    fecha_implementacion_decision: Mapped[date | None]
    responsable_decision_id: Mapped[int] = fk("usuario.id")
    estado_decision: Mapped[EstadoDecision] = enum_col(EstadoDecision, default=EstadoDecision.PROPUESTA)
    estado_plan_resultante_id: Mapped[int | None] = fk("estado_plan.id", nullable=True)  # ERD: DECISION }o--|| ESTADO_PLAN
    lecciones_aprendidas: Mapped[TXT | None]  # Slice C2 (aditivo): leccion aprendida por decision (v7 M7)

    evaluacion: Mapped[EvaluacionPlan] = relationship(back_populates="decisiones")


class NotaContinuidad(Entity, Base):
    """F10 componente 3: notas de continuidad institucional (texto cifrado)."""

    __tablename__ = "nota_continuidad"

    estudiante_id: Mapped[int] = fk("estudiante.id")
    plan_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)
    semestre_origen: Mapped[S20]
    semestre_destino: Mapped[S20 | None]
    destinatario: Mapped[DestinatarioNota] = enum_col(DestinatarioNota, default=DestinatarioNota.TODOS)
    contenido: Mapped[CTXT]  # cifrado
    estado: Mapped[EstadoNotaContinuidad] = enum_col(EstadoNotaContinuidad, default=EstadoNotaContinuidad.BORRADOR)
    elaborada_por_id: Mapped[int] = fk("usuario.id")
    aprobada_por_estudiante: Mapped[bool] = mapped_column(default=False)
    aprobada_at: Mapped[DT | None]
    motivo_rechazo: Mapped[TXT | None]
