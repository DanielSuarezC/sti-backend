"""Schemas de usuarios, programas y asignaturas (slice A, M1)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Rol

ROLES_GESTIONABLES = (Rol.ADMIN, Rol.BIENESTAR, Rol.COORDINADOR, Rol.DOCENTE)
TIPO_DOC = "^(CC|TI|PEP|CE|PA)$"
NIVEL = "^(TECNICO|TECNOLOGIA|PREGRADO|POSTGRADO)$"
ESCENARIO = "^(AULA|CAMPUS|VIRTUALIDAD|LABORATORIOS|PRACTICA_CLINICA|PRACTICA_SALUD_PUBLICA|EVENTOS|PASANTIAS)$"


class _Perfil(BaseModel):
    programa_id: int | None = None  # docente
    programas_ids: list[int] | None = None  # coordinador
    numero_empleado: str | None = Field(None, max_length=50)
    titulo_postgrado: str | None = Field(None, max_length=255)
    especialidad: str | None = Field(None, max_length=255)
    profesion: str | None = Field(None, max_length=100)
    especializacion: str | None = Field(None, max_length=255)
    cargo_administrativo: str | None = Field(None, max_length=100)
    area_responsable: str | None = Field(None, max_length=255)


class UsuarioCreate(_Perfil):
    email: EmailStr
    nombre_completo: str = Field(min_length=3, max_length=255)
    rol: Rol
    numero_documento: str | None = Field(None, max_length=50)
    tipo_documento: str | None = Field(None, pattern=TIPO_DOC)
    telefono: str | None = Field(None, max_length=20)

    @field_validator("rol")
    @classmethod
    def _rol(cls, v):
        if v not in ROLES_GESTIONABLES:
            raise ValueError("el rol debe ser ADMIN, BIENESTAR, COORDINADOR o DOCENTE (los estudiantes se crean por las tres vías)")
        return v


class UsuarioUpdate(_Perfil):
    email: EmailStr | None = None
    nombre_completo: str | None = Field(None, min_length=3, max_length=255)
    numero_documento: str | None = Field(None, max_length=50)
    tipo_documento: str | None = Field(None, pattern=TIPO_DOC)
    telefono: str | None = Field(None, max_length=20)


class MotivoBody(BaseModel):
    motivo: str | None = Field(None, max_length=500)


class EstudianteVia1(BaseModel):
    nombre_completo: str = Field(min_length=3, max_length=255)
    codigo_estudiante: str = Field(min_length=1, max_length=50)
    programa_id: int
    email: EmailStr
    telefono: str | None = Field(None, max_length=20)
    semestre_actual: int | None = Field(None, ge=1, le=20)
    consentimiento_verbal_declarado: bool

    @field_validator("consentimiento_verbal_declarado")
    @classmethod
    def _consent(cls, v):
        if v is not True:
            raise ValueError("debe declarar que el estudiante dio su consentimiento verbal para crear la cuenta")
        return v


class AsignacionCreate(BaseModel):
    asignatura_id: int
    semestre_academico: str = Field(pattern=r"^\d{4}-(I|II)$")
    grupo: str | None = Field(None, max_length=20)


class ProgramaCreate(BaseModel):
    nombre_programa: str = Field(min_length=2, max_length=255)
    codigo_programa: str = Field(min_length=1, max_length=50)
    descripcion_programa: str | None = None
    nivel_academico: str = Field("PREGRADO", pattern=NIVEL)
    duracion_semestres: int | None = Field(None, ge=1, le=20)
    total_creditos: int | None = Field(None, ge=1, le=400)
    facultad_responsable: str | None = Field(None, max_length=255)
    semestre_practicas: int | None = Field(None, ge=1, le=20)
    disponibilidad_ajustes_tea: bool = False
    capacitacion_docentes_tea: bool = False
    coordinador_usuario_id: int | None = None


class ProgramaUpdate(BaseModel):
    nombre_programa: str | None = Field(None, min_length=2, max_length=255)
    codigo_programa: str | None = Field(None, min_length=1, max_length=50)
    descripcion_programa: str | None = None
    nivel_academico: str | None = Field(None, pattern=NIVEL)
    duracion_semestres: int | None = Field(None, ge=1, le=20)
    total_creditos: int | None = Field(None, ge=1, le=400)
    facultad_responsable: str | None = Field(None, max_length=255)
    semestre_practicas: int | None = Field(None, ge=1, le=20)
    disponibilidad_ajustes_tea: bool | None = None
    capacitacion_docentes_tea: bool | None = None
    coordinador_usuario_id: int | None = None


class AsignaturaCreate(BaseModel):
    programa_id: int
    codigo: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=2, max_length=255)
    semestre_plan: int | None = Field(None, ge=1, le=20)
    creditos: int | None = Field(None, ge=0, le=30)
    escenario_predominante: str | None = Field(None, pattern=ESCENARIO)
    es_practica: bool = False


class AsignaturaUpdate(BaseModel):
    codigo: str | None = Field(None, min_length=1, max_length=50)
    nombre: str | None = Field(None, min_length=2, max_length=255)
    semestre_plan: int | None = Field(None, ge=1, le=20)
    creditos: int | None = Field(None, ge=0, le=30)
    escenario_predominante: str | None = Field(None, pattern=ESCENARIO)
    es_practica: bool | None = None
