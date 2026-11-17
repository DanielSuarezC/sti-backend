"""F6 - Plan MAAR-TEA: PLAN_MAAR_TEA, ESTRATEGIA_DUA, AJUSTE_RAZONABLE + 6 respuestas, ESTADO_PLAN (ERD §3.32-3.40, 3.53)
+ PLAN_VERSION, FIRMA_PLAN, TAREA_NEGOCIACION (v7 M5).

Notas de reconciliacion con el ERD
* Maquina de estados ampliada (BUILD_SPEC §4): ver `EstadoPlanEnum` y `app/services/plan_states.py`.
* "Un plan activo por estudiante y semestre": el UNIQUE(estudiante, semestre, estado) del ERD no lo garantiza;
  se implementa como indice unico parcial (estudiante_id, semestre_academico) sobre planes no eliminados y
  no ARCHIVADOS. Las versiones viven en PLAN_VERSION (snapshots), no como filas nuevas de plan.
* `profesionales_responsables_ids` (VARCHAR) -> lista JSON de ids de usuario.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    DT,
    JS,
    JSL,
    S20,
    S30,
    S50,
    S100,
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
    Corte,
    DimensionDua,
    Escenario,
    EspecificidadAjuste,
    EstadoAjuste,
    EstadoFirma,
    EstadoImplementacionDua,
    EstadoPlanEnum,
    EstadoTareaNegociacion,
    RolFirmante,
    Semaforo,
    TipoAjuste,
    TipoAmbientalAjuste,
    TipoComunicacionAjuste,
    TipoEvaluativoAjuste,
    TipoInteraccionAjuste,
    TipoPedagogicoAjuste,
    TipoTareaNegociacion,
    TipoTecnologicoAjuste,
)


class EstadoPlan(Entity, Base):
    """Catalogo de estados del plan (unico caso con DELETE fisico permitido, ERD §6.1)."""

    __tablename__ = "estado_plan"
    __allow_hard_delete__ = True

    nombre_estado: Mapped[S100] = mapped_column(unique=True)
    descripcion_estado: Mapped[TXT | None]
    transiciones_permitidas: Mapped[JSL | None]  # ERD: VARCHAR(500) -> lista JSON de nombres de estado


class PlanMaarTea(Entity, Base):
    __tablename__ = "plan_maar_tea"
    __table_args__ = (
        CheckConstraint("vigencia_fin IS NULL OR vigencia_fin > vigencia_inicio", name="ck_vigencia_plan"),
        Index("idx_plan_estudiante_semestre", "estudiante_id", "semestre_academico"),
        Index(
            "uq_plan_activo_estudiante_semestre",
            "estudiante_id",
            "semestre_academico",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND estado <> 'ARCHIVADO'"),
            postgresql_where=text("deleted_at IS NULL AND estado <> 'ARCHIVADO'"),
        ),
    )

    estudiante_id: Mapped[int] = fk("estudiante.id")
    fecha_elaboracion: Mapped[date]
    profesionales_responsables_ids: Mapped[JSL | None]
    participacion_estudiante: Mapped[bool] = mapped_column(default=True)
    participacion_familia: Mapped[bool] = mapped_column(default=False)
    semestre_academico: Mapped[S20]
    vigencia_inicio: Mapped[date]
    vigencia_fin: Mapped[date | None]
    resumen_ejecutivo: Mapped[TXT | None]
    justificacion_apoyos: Mapped[TXT | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[EstadoPlanEnum] = enum_col(EstadoPlanEnum, default=EstadoPlanEnum.BORRADOR)
    fecha_aprobacion: Mapped[date | None]
    aprobado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    elaborado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    validado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)  # Coordinador
    fecha_validacion: Mapped[DT | None]
    ciclos_negociacion: Mapped[int] = mapped_column(Integer, default=0)  # RF-25: maximo 3
    semaforo_actual: Mapped[Semaforo | None] = enum_col(Semaforo, nullable=True)  # cache del ultimo corte
    # --- slice C1 (aditivo): concertacion y participacion ---
    comentarios_validacion: Mapped[TXT | None]  # comentarios del Coordinador al devolver el plan
    enviado_a_estudiante_at: Mapped[DT | None]
    # [{"fecha","usuario_id","rol","accion","entidad","entidad_id","detalle"}]: quien propuso/modifico/respondio
    participacion_log: Mapped[JSL | None]

    estrategias_dua: Mapped[list[EstrategiaDua]] = relationship(back_populates="plan")
    ajustes: Mapped[list[AjusteRazonable]] = relationship(back_populates="plan")
    versiones: Mapped[list[PlanVersion]] = relationship(back_populates="plan")
    firmas: Mapped[list[FirmaPlan]] = relationship(back_populates="plan")


class EstrategiaDua(Entity, Base):
    """Estrategia DUA incluida en un plan (universal; ERD §3.33)."""

    __tablename__ = "estrategia_dua"

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    nombre_estrategia: Mapped[S200]
    descripcion: Mapped[TXT]
    dimension_dua: Mapped[DimensionDua] = enum_col(DimensionDua)  # ERD: dimensión_dua
    # ERD: NOT NULL; aqui nullable porque el borrador nace de sugerencias aun sin responsable asignado.
    responsable_implementacion_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    alcance: Mapped[S255 | None]
    fecha_inicio_implementacion: Mapped[date | None]
    estado_implementacion: Mapped[EstadoImplementacionDua] = enum_col(
        EstadoImplementacionDua, default=EstadoImplementacionDua.PLANEADA
    )
    estrategia_catalogo_id: Mapped[int | None] = fk("estrategia_dua_catalogo.id", nullable=True)
    sugerencia_id: Mapped[int | None] = fk("sugerencia_dua.id", nullable=True)
    asignatura_id: Mapped[int | None] = fk("asignatura.id", nullable=True)
    escenario: Mapped[Escenario | None] = enum_col(Escenario, nullable=True)
    # M3: registro de implementacion por el docente (si/no con nota)
    implementada: Mapped[bool | None]
    nota_implementacion: Mapped[TXT | None]
    implementada_at: Mapped[DT | None]
    implementada_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    # --- slice C1 (aditivo): trazabilidad de participacion y enlaces barrera/fortaleza (sin FK: ids de referencia) ---
    barrera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fortaleza_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origen: Mapped[S30 | None]  # BORRADOR_ASISTIDO | MANUAL | SUGERENCIA_DUA
    propuesta_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    propuesta_por_rol: Mapped[S20 | None]
    modificado_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modificado_at: Mapped[DT | None]

    plan: Mapped[PlanMaarTea] = relationship(back_populates="estrategias_dua")


class AjusteRazonable(Entity, Base):
    __tablename__ = "ajuste_razonable"
    __table_args__ = (
        CheckConstraint("fecha_fin_prevista IS NULL OR fecha_fin_prevista >= fecha_inicio",
                        name="ck_ajuste_fechas"),
    )

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    barrera_asociada_id: Mapped[int] = fk("barrera_identificada.id")
    nombre_ajuste: Mapped[S200]
    descripcion_ajuste: Mapped[TXT]
    justificacion: Mapped[TXT]
    tipo_ajuste: Mapped[TipoAjuste] = enum_col(TipoAjuste)
    especificidad: Mapped[EspecificidadAjuste] = enum_col(EspecificidadAjuste, default=EspecificidadAjuste.GENERAL)
    asignatura_si_aplica: Mapped[S200 | None]
    actividad_si_aplica: Mapped[S500 | None]
    fecha_inicio: Mapped[date]
    fecha_fin_prevista: Mapped[date | None]
    permanencia_indefinida: Mapped[bool] = mapped_column(default=True)
    estado: Mapped[EstadoAjuste] = enum_col(EstadoAjuste, default=EstadoAjuste.PROPUESTO)
    # --- v7 M5: campos por ajuste ---
    asignatura_id: Mapped[int | None] = fk("asignatura.id", nullable=True)  # alcance del docente
    responsable_id: Mapped[int | None] = fk("usuario.id", nullable=True)  # responsable principal (docente/otro)
    fortaleza_apoyo_id: Mapped[int | None] = fk("fortaleza.id", nullable=True)  # fortaleza en que se apoya
    frecuencia: Mapped[S200 | None]
    indicador_efectividad: Mapped[TXT | None]
    aceptado_por_estudiante: Mapped[bool | None]
    aceptado_por_estudiante_at: Mapped[DT | None]
    aceptado_por_responsable: Mapped[bool | None]
    aceptado_por_responsable_at: Mapped[DT | None]
    semaforo_actual: Mapped[Semaforo | None] = enum_col(Semaforo, nullable=True)
    # --- slice C1 (aditivo): recurso, participacion y respuestas de concertacion ---
    recurso: Mapped[S500 | None]
    origen: Mapped[S30 | None]  # BORRADOR_ASISTIDO | MANUAL
    propuesto_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    propuesto_por_rol: Mapped[S20 | None]  # BIENESTAR | SISTEMA | ...
    modificado_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modificado_at: Mapped[DT | None]
    respuesta_estudiante: Mapped[S30 | None]  # ACEPTADO | MODIFICACION_PROPUESTA | OBJETADO
    comentario_estudiante: Mapped[TXT | None]
    modificacion_propuesta: Mapped[TXT | None]
    comentario_responsable: Mapped[TXT | None]  # comentario del docente al aceptar/declinar

    plan: Mapped[PlanMaarTea] = relationship(back_populates="ajustes")
    resp_comunicacion: Mapped[list[RespuestaComunicacion]] = relationship(back_populates="ajuste")
    resp_pedagogia: Mapped[list[RespuestaPedagogia]] = relationship(back_populates="ajuste")
    resp_evaluacion: Mapped[list[RespuestaEvaluacion]] = relationship(back_populates="ajuste")
    resp_ambiente: Mapped[list[RespuestaAmbiente]] = relationship(back_populates="ajuste")
    resp_interaccion: Mapped[list[RespuestaInteraccion]] = relationship(back_populates="ajuste")
    resp_tecnologia: Mapped[list[RespuestaTecnologia]] = relationship(back_populates="ajuste")


class RespuestaComunicacion(Entity, Base):
    __tablename__ = "respuesta_comunicacion"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_comunicacion_ajuste: Mapped[TipoComunicacionAjuste] = enum_col(TipoComunicacionAjuste)
    especificacion: Mapped[TXT | None]

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_comunicacion")


class RespuestaPedagogia(Entity, Base):
    __tablename__ = "respuesta_pedagogia"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_pedagogico_ajuste: Mapped[TipoPedagogicoAjuste] = enum_col(TipoPedagogicoAjuste)
    descripcion: Mapped[TXT | None]

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_pedagogia")


class RespuestaEvaluacion(Entity, Base):
    __tablename__ = "respuesta_evaluacion"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_evaluativo_ajuste: Mapped[TipoEvaluativoAjuste] = enum_col(TipoEvaluativoAjuste)
    descripcion_especifica: Mapped[TXT | None]

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_evaluacion")


class RespuestaAmbiente(Entity, Base):
    __tablename__ = "respuesta_ambiente"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_ambiental_ajuste: Mapped[TipoAmbientalAjuste] = enum_col(TipoAmbientalAjuste)
    descripcion: Mapped[TXT | None]

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_ambiente")


class RespuestaInteraccion(Entity, Base):
    __tablename__ = "respuesta_interaccion"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_interaccion_ajuste: Mapped[TipoInteraccionAjuste] = enum_col(TipoInteraccionAjuste)
    descripcion: Mapped[TXT | None]

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_interaccion")


class RespuestaTecnologia(Entity, Base):
    __tablename__ = "respuesta_tecnologia"

    ajuste_id: Mapped[int] = fk("ajuste_razonable.id")
    tipo_tecnologico_ajuste: Mapped[TipoTecnologicoAjuste] = enum_col(TipoTecnologicoAjuste)
    descripcion_tecnologia: Mapped[TXT | None]
    soporte_tecnico_requerido: Mapped[bool] = mapped_column(default=False)

    ajuste: Mapped[AjusteRazonable] = relationship(back_populates="resp_tecnologia")


class PlanVersion(Entity, Base):
    """Historial de versiones del plan (M5): snapshot JSON inmutable por version."""

    __tablename__ = "plan_version"
    __table_args__ = (unique_active("uq_plan_version", "plan_id", "version"),)

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    version: Mapped[int] = mapped_column(Integer)
    estado_plan: Mapped[S50]
    snapshot: Mapped[JS]
    hash_snapshot: Mapped[S100]  # SHA-256 del snapshot canonico (lo que firman los actores)
    motivo_cambio: Mapped[TXT | None]
    creado_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)

    plan: Mapped[PlanMaarTea] = relationship(back_populates="versiones")


class FirmaPlan(Entity, Base):
    """Firma digital del plan por Estudiante, Bienestar y Coordinador (RF-24)."""

    __tablename__ = "firma_plan"
    __table_args__ = (unique_active("uq_firma_plan_version_rol", "plan_id", "version", "rol_firmante"),)

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    version: Mapped[int] = mapped_column(Integer)
    rol_firmante: Mapped[RolFirmante] = enum_col(RolFirmante)
    firmante_id: Mapped[int] = fk("usuario.id")
    firmado_at: Mapped[DT]
    hash_documento: Mapped[S100]
    firma_hash: Mapped[S100]
    ip: Mapped[S50 | None]
    user_agent: Mapped[S255 | None]
    estado: Mapped[EstadoFirma] = enum_col(EstadoFirma, default=EstadoFirma.FIRMADA)

    plan: Mapped[PlanMaarTea] = relationship(back_populates="firmas")


class TareaNegociacion(Entity, Base):
    """Desacuerdo del estudiante (max 3 ciclos -> Comite de Inclusion), concertacion en Amarillo y rediseno en Rojo."""

    __tablename__ = "tarea_negociacion"
    __table_args__ = (CheckConstraint("ciclo >= 1 AND ciclo <= 3", name="ck_tarea_negociacion_ciclo"),)

    plan_id: Mapped[int] = fk("plan_maar_tea.id")
    ajuste_id: Mapped[int | None] = fk("ajuste_razonable.id", nullable=True)
    tipo: Mapped[TipoTareaNegociacion] = enum_col(TipoTareaNegociacion, default=TipoTareaNegociacion.OBJECION_AJUSTE)
    estado: Mapped[EstadoTareaNegociacion] = enum_col(EstadoTareaNegociacion, default=EstadoTareaNegociacion.ABIERTA)
    ciclo: Mapped[int] = mapped_column(Integer, default=1)
    corte: Mapped[Corte | None] = enum_col(Corte, nullable=True)
    objecion_estudiante: Mapped[TXT | None]
    propuesta_bienestar: Mapped[TXT | None]
    resolucion: Mapped[TXT | None]
    # [{"ciclo":1,"objecion":"...","propuesta":"...","fecha":"..."}]
    historial: Mapped[JSL | None]
    creada_por_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    asignada_a_id: Mapped[int | None] = fk("usuario.id", nullable=True)
    fecha_limite: Mapped[date | None]
    resuelta_at: Mapped[DT | None]
    escalada_at: Mapped[DT | None]
