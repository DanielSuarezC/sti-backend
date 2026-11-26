"""Usuarios y roles: USUARIO, ESTUDIANTE, DOCENTE, COORDINADOR_PROGRAMA, PERSONAL_ADMINISTRATIVO,
PERSONAL_BIENESTAR (ERD §3.1, 3.2, 3.66-3.69) + REFRESH_TOKEN y PREFERENCIA_SENSORIAL_UI.

Decision: el ERD no define `programa_id` en USUARIO; el vinculo con el programa vive en
ESTUDIANTE.programa_id, DOCENTE.programa_id y COORDINADOR_PROGRAMA.programa_responsable_ids
(evita el ciclo usuario -> programa -> coordinador -> usuario).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    CDATE,
    CTXT,
    DT,
    JSL,
    S20,
    S50,
    S100,
    S255,
    Base,
    Entity,
    IdMixin,
    TimestampMixin,
    enum_col,
    fk,
    utcnow,
)
from app.models.enums import (
    EspaciadoUI,
    EstadoAcademico,
    EstadoUsuario,
    FuenteSSO,
    FuenteUI,
    GradoCompromiso,
    Rol,
    TipoDocumento,
    ViaIngreso,
)


class Usuario(Entity, Base):
    """Entidad base de todo actor (ERD §3.1)."""

    __tablename__ = "usuario"
    __table_args__ = (Index("ix_usuario_rol_estado", "rol", "estado"),)

    email: Mapped[S255] = mapped_column(unique=True, index=True)
    nombre_completo: Mapped[S255]
    numero_documento: Mapped[S50 | None] = mapped_column(unique=True)
    tipo_documento: Mapped[TipoDocumento | None] = enum_col(TipoDocumento, nullable=True)
    telefono: Mapped[S20 | None]
    rol: Mapped[Rol] = enum_col(Rol)
    estado: Mapped[EstadoUsuario] = enum_col(EstadoUsuario, default=EstadoUsuario.PENDIENTE_ACTIVACION)
    fecha_ultima_sesion: Mapped[DT | None]  # ERD: fecha_ultima_sesion (fecha_registro == created_at)

    # --- autenticacion ---
    password_hash: Mapped[S255 | None]
    password_changed_at: Mapped[DT | None]
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[DT | None]
    activation_token_hash: Mapped[S100 | None] = mapped_column(index=True)
    activation_expires_at: Mapped[DT | None]
    reset_token_hash: Mapped[S100 | None] = mapped_column(index=True)
    reset_expires_at: Mapped[DT | None]
    recovery_code_hash: Mapped[S100 | None]  # código de recuperación (sin correo); solo el hash
    auth_source: Mapped[FuenteSSO] = enum_col(FuenteSSO, default=FuenteSSO.LOCAL)
    sso_subject: Mapped[S255 | None] = mapped_column(unique=True)

    estudiante: Mapped[Estudiante | None] = relationship(
        back_populates="usuario", uselist=False, foreign_keys="Estudiante.usuario_id"
    )
    docente: Mapped[Docente | None] = relationship(back_populates="usuario", uselist=False)
    coordinador: Mapped[CoordinadorPrograma | None] = relationship(back_populates="usuario", uselist=False)
    bienestar: Mapped[PersonalBienestar | None] = relationship(back_populates="usuario", uselist=False)
    administrativo: Mapped[PersonalAdministrativo | None] = relationship(back_populates="usuario", uselist=False)
    preferencias_ui: Mapped[PreferenciaSensorialUI | None] = relationship(back_populates="usuario", uselist=False)

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utcnow()


class Estudiante(Entity, Base):
    """Estudiante con TEA matriculado (ERD §3.2). Campos de diagnostico cifrados."""

    __tablename__ = "estudiante"
    __table_args__ = (Index("ix_estudiante_programa_estado", "programa_id", "estado_academico"),)

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    programa_id: Mapped[int | None] = fk("programa_academico.id", nullable=True)
    codigo_estudiante: Mapped[S50] = mapped_column(unique=True, index=True)
    fecha_diagnostico_tea: Mapped[CDATE | None]  # cifrado
    tipo_tea_caracterizacion: Mapped[CTXT | None]  # cifrado
    institucion_diagnostico: Mapped[CTXT | None]  # cifrado
    familia_autoriza_participacion: Mapped[bool] = mapped_column(default=False)
    contacto_emergencia: Mapped[S255 | None]
    anio_ingreso: Mapped[int] = mapped_column(Integer, default=lambda: utcnow().year)  # ERD: año_ingreso
    estado_academico: Mapped[EstadoAcademico] = enum_col(EstadoAcademico, default=EstadoAcademico.ACTIVO)
    via_ingreso: Mapped[ViaIngreso] = enum_col(ViaIngreso, default=ViaIngreso.BIENESTAR)
    semestre_actual: Mapped[int | None] = mapped_column(Integer)
    bienestar_asignado_id: Mapped[int | None] = fk("usuario.id", nullable=True)

    usuario: Mapped[Usuario] = relationship(back_populates="estudiante", foreign_keys=[usuario_id])
    programa: Mapped[ProgramaAcademico | None] = relationship(foreign_keys=[programa_id])  # type: ignore[name-defined]  # noqa: F821


class Docente(Entity, Base):
    __tablename__ = "docente"

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    programa_id: Mapped[int | None] = fk("programa_academico.id", nullable=True)
    numero_empleado: Mapped[S50 | None]
    titulo_postgrado: Mapped[S255 | None]
    especialidad: Mapped[S255 | None]
    anios_experiencia_docente: Mapped[int | None] = mapped_column(Integer)  # ERD: años_experiencia_docente
    capacitacion_dua: Mapped[bool] = mapped_column(default=False)
    capacitacion_tea: Mapped[bool] = mapped_column(default=False)
    disponibilidad_actualizacion: Mapped[bool] = mapped_column(default=False)
    grado_compromiso_inclusion: Mapped[GradoCompromiso] = enum_col(GradoCompromiso, default=GradoCompromiso.MEDIO)

    usuario: Mapped[Usuario] = relationship(back_populates="docente")


class CoordinadorPrograma(Entity, Base):
    __tablename__ = "coordinador_programa"

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    # ERD: VARCHAR(500) con ids separados por coma -> lista JSON de ids de programa
    programa_responsable_ids: Mapped[JSL | None]
    anios_en_coordinacion: Mapped[int | None] = mapped_column(Integer)  # ERD: años_en_coordinacion

    usuario: Mapped[Usuario] = relationship(back_populates="coordinador")


class PersonalAdministrativo(Entity, Base):
    """Perfil del personal administrativo (rol ADMIN del sistema)."""

    __tablename__ = "personal_administrativo"

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    cargo_administrativo: Mapped[S100 | None]
    area_responsable: Mapped[S255 | None]
    capacitacion_inclusion: Mapped[bool] = mapped_column(default=False)

    usuario: Mapped[Usuario] = relationship(back_populates="administrativo")


class PersonalBienestar(Entity, Base):
    __tablename__ = "personal_bienestar"

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    profesion: Mapped[S100 | None]
    especializacion: Mapped[S255 | None]
    anios_experiencia: Mapped[int | None] = mapped_column(Integer)  # ERD: años_experiencia
    caseload_actual: Mapped[int | None] = mapped_column(Integer)

    usuario: Mapped[Usuario] = relationship(back_populates="bienestar")


class RefreshToken(IdMixin, TimestampMixin, Base):
    """Refresh token con rotacion. Se guarda solo el hash SHA-256; `family_id` agrupa la cadena de rotacion.

    Reuso de un token ya rotado => se revoca toda la familia (deteccion de robo).
    """

    __tablename__ = "refresh_token"

    usuario_id: Mapped[int] = fk("usuario.id")
    token_hash: Mapped[S100] = mapped_column(unique=True, index=True)
    family_id: Mapped[S50] = mapped_column(index=True)
    expires_at: Mapped[DT]
    revoked_at: Mapped[DT | None]
    replaced_by_id: Mapped[int | None] = mapped_column(Integer)
    user_agent: Mapped[S255 | None]
    ip: Mapped[S50 | None]

    usuario: Mapped[Usuario] = relationship()


class PreferenciaSensorialUI(Entity, Base):
    """Panel 'Como me siento mejor' (DESIGN.md): preferencias de interfaz por usuario."""

    __tablename__ = "preferencia_sensorial_ui"
    __table_args__ = (
        CheckConstraint("tamano_texto IN (100, 115, 130)", name="ck_preferencia_sensorial_ui_tamano_texto_valores"),
    )

    usuario_id: Mapped[int] = fk("usuario.id", unique=True)
    modo_calma: Mapped[bool] = mapped_column(default=False)
    tamano_texto: Mapped[int] = mapped_column(Integer, default=100)
    espaciado: Mapped[EspaciadoUI] = enum_col(EspaciadoUI, default=EspaciadoUI.NORMAL)
    sin_movimiento: Mapped[bool] = mapped_column(default=False)
    alto_contraste: Mapped[bool] = mapped_column(default=False)
    fuente: Mapped[FuenteUI] = enum_col(FuenteUI, default=FuenteUI.PREDETERMINADA)

    usuario: Mapped[Usuario] = relationship(back_populates="preferencias_ui")
