"""Fábricas de datos para pruebas (usuarios por rol, programa, consentimiento, plan mínimo)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models import (
    AjusteRazonable,
    AsignacionDocente,
    Asignatura,
    AutorizacionFamiliar,
    BarreraIdentificada,
    Consentimiento,
    Docente,
    Estudiante,
    PlanMaarTea,
    ProgramaAcademico,
    Usuario,
)
from app.models.base import utcnow
from app.models.enums import (
    EstadoAutorizacionFamiliar,
    EstadoConsentimiento,
    EstadoPlanEnum,
    EstadoUsuario,
    Rol,
    TipoAjuste,
    TipoBarrera,
)
from app.services.accounts import create_user

PASSWORD = "Clave12345!"
_seq = itertools.count(1)


def make_programa(db: Session, nombre: str = "Enfermería", codigo: str | None = None) -> ProgramaAcademico:
    n = next(_seq)
    p = ProgramaAcademico(nombre_programa=nombre, codigo_programa=codigo or f"PRG{n:03d}")
    db.add(p)
    db.flush()
    return p


def make_user(db: Session, rol: Rol, *, email: str | None = None, password: str = PASSWORD,
              estado: EstadoUsuario | None = None, perfil: dict | None = None, nombre: str | None = None) -> Usuario:
    n = next(_seq)
    u = create_user(
        db, email=email or f"{str(rol).lower()}{n}@example.com", nombre_completo=nombre or f"{rol} {n}",
        rol=rol, password=password, estado=estado or EstadoUsuario.ACTIVO, perfil=perfil,
    )
    db.commit()
    return u


def make_estudiante(db: Session, programa: ProgramaAcademico, *, consent: bool = True, **kw) -> tuple[Usuario, Estudiante]:
    n = next(_seq)
    u = make_user(
        db, Rol.ESTUDIANTE, perfil={"codigo_estudiante": f"E{n:05d}", "programa_id": programa.id},
        estado=EstadoUsuario.ACTIVO if consent else EstadoUsuario.PENDIENTE_CONSENTIMIENTO, **kw,
    )
    est = db.query(Estudiante).filter_by(usuario_id=u.id).one()
    if consent:
        sign_consent(db, est, u)
    return u, est


def sign_consent(db: Session, est: Estudiante, user: Usuario) -> Consentimiento:
    c = Consentimiento(
        estudiante_id=est.id, version_texto="F0-v1", texto_hash="0" * 64, acepta_tratamiento_datos_sensibles=True,
        acepta_politica_privacidad=True, firmado_at=utcnow(), firma_hash="1" * 64, firmado_por_id=user.id,
        estado=EstadoConsentimiento.FIRMADO,
    )
    db.add(c)
    db.commit()
    return c


def make_plan_with_ajuste(db: Session, est: Estudiante, bienestar: Usuario, *, asignatura: Asignatura | None = None,
                          estado: EstadoPlanEnum = EstadoPlanEnum.APROBADO) -> tuple[PlanMaarTea, AjusteRazonable]:
    barrera = BarreraIdentificada(
        estudiante_id=est.id, tipo_barrera=TipoBarrera.SENSORIAL, descripcion_barrera="Ruido en el aula",
        fecha_identificacion=date.today(),
    )
    db.add(barrera)
    db.flush()
    plan = PlanMaarTea(
        estudiante_id=est.id, fecha_elaboracion=date.today(), semestre_academico="2026-II",
        vigencia_inicio=date.today(), estado=estado, elaborado_por_id=bienestar.id,
    )
    db.add(plan)
    db.flush()
    ajuste = AjusteRazonable(
        plan_id=plan.id, barrera_asociada_id=barrera.id, nombre_ajuste="Ubicación cerca de la puerta",
        descripcion_ajuste="Puede sentarse junto a la salida", justificacion="Reduce ruido y sobrecarga",
        tipo_ajuste=TipoAjuste.AMBIENTE, fecha_inicio=date.today(), asignatura_id=asignatura.id if asignatura else None,
    )
    db.add(ajuste)
    db.commit()
    return plan, ajuste


@dataclass
class World:
    programa: ProgramaAcademico
    otro_programa: ProgramaAcademico
    admin: Usuario
    bienestar: Usuario
    coordinador: Usuario
    coordinador_otro: Usuario
    docente: Usuario
    docente_otro: Usuario
    estudiante_user: Usuario
    estudiante: Estudiante
    otro_estudiante_user: Usuario
    otro_estudiante: Estudiante
    familiar: Usuario
    asignatura: Asignatura
    extras: dict = field(default_factory=dict)


def build_world(db: Session) -> World:
    prog = make_programa(db, "Enfermería")
    otro = make_programa(db, "Medicina")
    admin = make_user(db, Rol.ADMIN)
    bienestar = make_user(db, Rol.BIENESTAR)
    coord = make_user(db, Rol.COORDINADOR, perfil={"programa_responsable_ids": [prog.id]})
    coord_otro = make_user(db, Rol.COORDINADOR, perfil={"programa_responsable_ids": [otro.id]})
    doc = make_user(db, Rol.DOCENTE, perfil={"programa_id": prog.id})
    doc_otro = make_user(db, Rol.DOCENTE, perfil={"programa_id": prog.id})
    eu, est = make_estudiante(db, prog)
    eu2, est2 = make_estudiante(db, prog)
    fam = make_user(db, Rol.FAMILIAR)
    asig = Asignatura(programa_id=prog.id, codigo="ENF101", nombre="Fundamentos de Enfermería")
    db.add(asig)
    db.flush()
    d = db.query(Docente).filter_by(usuario_id=doc.id).one()
    db.add(AsignacionDocente(docente_id=d.id, asignatura_id=asig.id, semestre_academico="2026-II"))
    db.commit()
    return World(prog, otro, admin, bienestar, coord, coord_otro, doc, doc_otro, eu, est, eu2, est2, fam, asig)


def authorize_familiar(db: Session, est: Estudiante, familiar: Usuario, alcance: list[str]) -> AutorizacionFamiliar:
    a = AutorizacionFamiliar(
        estudiante_id=est.id, familiar_usuario_id=familiar.id, familiar_nombre=familiar.nombre_completo,
        familiar_email=familiar.email, parentesco="Madre", alcance=alcance, estado=EstadoAutorizacionFamiliar.VIGENTE,
        otorgada_at=utcnow(),
    )
    db.add(a)
    db.commit()
    return a


def auth_headers(user: Usuario) -> dict[str, str]:
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}
