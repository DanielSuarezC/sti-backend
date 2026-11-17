"""F10 - Cierre de semestre / continuidad (slice C3): cabecera del formato F10 por estudiante y semestre.

El ERD no tiene una entidad para el F10 como formato (solo TRAYECTORIA_ACADEMICA, HITO_TRAYECTORIA, NOTA_CONTINUIDAD y
DECISION_PLAN). Esta tabla aditiva guarda lo que no cabe en ellas:

* componente 1 (actualizacion del plan): decisiones por ajuste/estrategia para el siguiente semestre (`actualizacion_plan`);
* componente 2 (trayectoria): referencia a TRAYECTORIA_ACADEMICA del semestre y la proyeccion/necesidades anticipadas;
* componente 3 (notas de continuidad): viven en NOTA_CONTINUIDAD (cifradas) y se enlazan por (estudiante, semestre_origen);
* la doble aprobacion (Bienestar + Estudiante) con sello de tiempo y el plan del siguiente semestre que se genero.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.orm import Mapped

from app.models.base import DT, JS, JSL, S20, TXT, Base, Entity, enum_col, fk, unique_active


class EstadoF10(StrEnum):
    BORRADOR = "BORRADOR"  # generado / en edicion (sin aprobaciones o con aprobaciones invalidadas por un cambio)
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"  # aprobo uno de los dos (Bienestar o Estudiante)
    APROBADO = "APROBADO"  # aprobaron ambos: alimenta el F3 del siguiente semestre


class F10Semestre(Entity, Base):
    __tablename__ = "f10_semestre"
    __table_args__ = (unique_active("uq_f10_estudiante_semestre_origen", "estudiante_id", "semestre_origen"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    semestre_origen: Mapped[S20]  # semestre que se cierra
    semestre_destino: Mapped[S20]  # semestre que inicia
    estado: Mapped[EstadoF10] = enum_col(EstadoF10, default=EstadoF10.BORRADOR)
    plan_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)  # plan del semestre de origen
    evaluacion_id: Mapped[int | None] = fk("evaluacion_plan.id", nullable=True)  # F9 del que parte el borrador
    trayectoria_id: Mapped[int | None] = fk("trayectoria_academica.id", nullable=True)
    plan_siguiente_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)  # creado al aprobar (BORRADOR)
    # {"items":[{elemento,elemento_id,nombre,tipo_decision,...}], "nuevos_propuestos":[str], "observaciones": str|None}
    actualizacion_plan: Mapped[JS]
    # [{"tipo":"PRACTICAS|PASANTIAS|TRABAJO_GRADO|OTRA","semestre_estimado","descripcion","apoyos_previstos","origen"}]
    necesidades_anticipadas: Mapped[JSL]
    proyeccion: Mapped[JS | None]  # proyeccion hacia graduacion + necesidades del siguiente semestre (plan de estudios)
    generado_at: Mapped[DT]
    elaborado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    aprobado_bienestar_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    aprobado_bienestar_at: Mapped[DT | None]
    aprobado_estudiante_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    aprobado_estudiante_at: Mapped[DT | None]
    comentario_estudiante: Mapped[TXT | None]
    aprobado_at: Mapped[DT | None]  # momento en que quedo APROBADO (segunda aprobacion)
