"""Motor DUA (M3): ESTRATEGIA_DUA_CATALOGO, SUGERENCIA_DUA, CASO_CBR.

El catalogo se filtra por escenario/tipo de barrera en SERVICIO (listas JSON): es portable entre SQLite y
PostgreSQL y el catalogo es pequeno (decenas/cientos de filas). Ningun campo de estas tablas contiene datos de
identidad del estudiante: CASO_CBR guarda solo el perfil abstracto (tipos de barrera, escenarios, principios).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Float, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    DT,
    JS,
    JSL,
    S20,
    S50,
    S200,
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
    Escenario,
    EstadoSugerencia,
    OrigenSugerencia,
    PrincipioDua,
    Semaforo,
    TipoBarrera,
)


class EstrategiaDuaCatalogo(Entity, Base):
    """Estrategia del catalogo institucional DUA (CAST 2.2: 3 principios, 9 pautas, 31 puntos de verificacion)."""

    __tablename__ = "estrategia_dua_catalogo"
    __table_args__ = (
        CheckConstraint("pauta >= 1 AND pauta <= 9", name="ck_estrategia_dua_catalogo_pauta"),
        unique_active("uq_catalogo_dua_codigo", "codigo"),
        Index("ix_catalogo_dua_principio_pauta", "principio", "pauta"),
    )

    codigo: Mapped[S50]  # p. ej. "DUA-R-1.1-01"
    nombre: Mapped[S255]
    descripcion_pedagogica: Mapped[TXT]
    principio: Mapped[PrincipioDua] = enum_col(PrincipioDua)
    pauta: Mapped[int] = mapped_column(Integer)  # 1..9 (CAST 2.2)
    pauta_nombre: Mapped[S200 | None]
    punto_verificacion: Mapped[S20 | None]  # p. ej. "1.1"
    escenarios: Mapped[JSL]  # lista de Escenario
    tipos_barrera: Mapped[JSL]  # lista de TipoBarrera
    perfil_estudiante: Mapped[TXT | None]  # perfil para el que es mas pertinente
    fuente: Mapped[S500 | None]
    activo: Mapped[bool] = mapped_column(default=True)


class SugerenciaDua(Entity, Base):
    """Sugerencia del motor M3 para un estudiante. Bienestar acepta, modifica o rechaza (con motivo)."""

    __tablename__ = "sugerencia_dua"
    __table_args__ = (Index("ix_sugerencia_estudiante_estado", "estudiante_id", "estado"),)

    estudiante_id: Mapped[int] = fk("estudiante.id")
    plan_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)
    barrera_id: Mapped[int | None] = fk("barrera_identificada.id", nullable=True)
    estrategia_catalogo_id: Mapped[int] = fk("estrategia_dua_catalogo.id")
    tipo_barrera: Mapped[TipoBarrera | None] = enum_col(TipoBarrera, nullable=True)
    escenario: Mapped[Escenario | None] = enum_col(Escenario, nullable=True)
    principio_dua: Mapped[PrincipioDua] = enum_col(PrincipioDua)
    origen: Mapped[OrigenSugerencia] = enum_col(OrigenSugerencia, default=OrigenSugerencia.FILTRO_CATALOGO)
    puntaje_similitud: Mapped[float | None] = mapped_column(Float)
    justificacion: Mapped[TXT | None]  # "Pertinente porque la barrera es COMUNICATIVA en el escenario AULA"
    texto_accesible: Mapped[TXT | None]  # texto adaptado (IA o plantilla)
    estado: Mapped[EstadoSugerencia] = enum_col(EstadoSugerencia, default=EstadoSugerencia.PROPUESTA)
    motivo_decision: Mapped[TXT | None]  # obligatorio al rechazar/modificar
    texto_modificado: Mapped[TXT | None]
    decidido_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    decidido_at: Mapped[DT | None]


class CasoCbr(Entity, Base):
    """Caso del motor CBR (scikit-learn). Anonimo: solo perfil abstracto + resultado de la estrategia."""

    __tablename__ = "caso_cbr"
    __table_args__ = (Index("ix_caso_cbr_estrategia", "estrategia_catalogo_id"),)

    estrategia_catalogo_id: Mapped[int] = fk("estrategia_dua_catalogo.id")
    # {"tipos_barrera": [...], "escenarios": [...], "principios": [...], "severidad_max": "MODERADA", ...}
    perfil: Mapped[JS]
    resultado_semaforo: Mapped[Semaforo | None] = enum_col(Semaforo, nullable=True)
    exitoso: Mapped[bool] = mapped_column(default=True)
    peso: Mapped[float] = mapped_column(Float, default=1.0)
    semestre_academico: Mapped[S20 | None]
    plan_id: Mapped[int | None] = fk("plan_maar_tea.id", nullable=True)  # trazabilidad interna (sin identidad)
    origen: Mapped[S50 | None]  # "F9", "SEED", "IMPORTACION"
    fecha_caso: Mapped[date | None]
