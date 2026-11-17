"""Matriz de acceso por rol (arquitectura v7 §12.1) y chequeos de alcance por objeto.

Dos capas:
1. MATRIZ: (rol, recurso) -> acciones permitidas (contrato de §12.1; cualquier cambio es un cambio de requisito).
2. ALCANCE: ¿el usuario está vinculado a ESE estudiante? (programa, asignación, autorización familiar, ser el propio).

Uso típico en un router::

    est = get_estudiante_or_404(db, estudiante_id)
    assert_can(db, user, estudiante_id, Recurso.CARACTERIZACION, Accion.LEER)

Los datos del estudiante (todo salvo DATOS_BASICOS) exigen además F0 firmado del estudiante (RF-05).
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConsentRequired, Forbidden, NotFound
from app.models.academico import AsignacionDocente
from app.models.base import utcnow
from app.models.consentimiento import AutorizacionFamiliar, Consentimiento
from app.models.enums import (
    AlcanceFamiliar,
    EstadoAutorizacionFamiliar,
    EstadoConsentimiento,
    EstadoPlanEnum,
    Rol,
)
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea
from app.models.usuarios import CoordinadorPrograma, Docente, Estudiante, Usuario


class Recurso(StrEnum):
    DATOS_BASICOS = "DATOS_BASICOS"  # identidad mínima (nombre, código, programa); sin datos clínicos
    AQ10 = "AQ10"  # resultado del AQ-10
    CARACTERIZACION = "CARACTERIZACION"  # F1 + F2 + diagnóstico
    CONTEXTO = "CONTEXTO"  # F3
    BARRERAS = "BARRERAS"  # F4
    FACILITADORES = "FACILITADORES"  # F5
    PLAN = "PLAN"  # F6 / F7
    SEGUIMIENTO = "SEGUIMIENTO"  # F8
    EVALUACION = "EVALUACION"  # F9
    NOTAS_CONTINUIDAD = "NOTAS_CONTINUIDAD"  # F10 notas
    TRAYECTORIA = "TRAYECTORIA"  # F10 trayectoria
    CATALOGO_DUA = "CATALOGO_DUA"  # no ligado a estudiante
    AUDITORIA = "AUDITORIA"  # no ligado a estudiante


class Accion(StrEnum):
    LEER = "LEER"
    ESCRIBIR = "ESCRIBIR"  # crear/editar/archivar (CRUD)
    APORTAR = "APORTAR"  # el estudiante/coordinador aporta información propia en un formato compartido
    VALIDAR = "VALIDAR"  # coordinador valida el plan
    FIRMAR = "FIRMAR"
    CONCERTAR = "CONCERTAR"  # estudiante acepta/objeta/propone cambios al plan
    ACEPTAR_RESPONSABILIDAD = "ACEPTAR_RESPONSABILIDAD"  # docente acepta sus responsabilidades en el plan
    REGISTRAR_IMPLEMENTACION = "REGISTRAR_IMPLEMENTACION"  # docente registra implementación
    PERCEPCION = "PERCEPCION"  # estudiante registra su percepción en el seguimiento
    APROBAR = "APROBAR"  # estudiante aprueba notas de continuidad


L, E, A = Accion.LEER, Accion.ESCRIBIR, Accion.APORTAR
_R, _W = frozenset({L}), frozenset({L, E})

#: Matriz §12.1 (+ filas F3/F5/F9/trayectoria derivadas de los pasos del modelo: ver docs/MODELO.md)
MATRIZ: dict[tuple[Rol, Recurso], frozenset[Accion]] = {
    # --- Datos básicos (no clínicos) ---
    (Rol.ADMIN, Recurso.DATOS_BASICOS): _R,
    (Rol.BIENESTAR, Recurso.DATOS_BASICOS): _W,
    (Rol.COORDINADOR, Recurso.DATOS_BASICOS): _R,
    (Rol.DOCENTE, Recurso.DATOS_BASICOS): _R,  # solo estudiantes con plan visible en sus asignaturas
    (Rol.ESTUDIANTE, Recurso.DATOS_BASICOS): _R,
    # --- AQ-10: Admin config solo; Bienestar lectura; Estudiante lectura propia ---
    (Rol.BIENESTAR, Recurso.AQ10): _W,
    (Rol.ESTUDIANTE, Recurso.AQ10): frozenset({L, A}),  # autoaplicación + lectura propia
    # --- Caracterización F1-F2 ---
    (Rol.BIENESTAR, Recurso.CARACTERIZACION): _W,
    (Rol.COORDINADOR, Recurso.CARACTERIZACION): _R,
    (Rol.ESTUDIANTE, Recurso.CARACTERIZACION): frozenset({L, A}),
    (Rol.FAMILIAR, Recurso.CARACTERIZACION): _R,  # si el estudiante autoriza
    # --- Contexto F3 (Bienestar + Coordinador) ---
    (Rol.BIENESTAR, Recurso.CONTEXTO): _W,
    (Rol.COORDINADOR, Recurso.CONTEXTO): frozenset({L, A}),
    (Rol.ESTUDIANTE, Recurso.CONTEXTO): _R,
    # --- Barreras F4 / Facilitadores F5 ---
    (Rol.BIENESTAR, Recurso.BARRERAS): _W,
    (Rol.COORDINADOR, Recurso.BARRERAS): _R,
    (Rol.ESTUDIANTE, Recurso.BARRERAS): frozenset({L, A}),
    (Rol.BIENESTAR, Recurso.FACILITADORES): _W,
    (Rol.COORDINADOR, Recurso.FACILITADORES): _R,
    (Rol.ESTUDIANTE, Recurso.FACILITADORES): frozenset({L, A}),
    # --- Plan MAAR-TEA F6/F7 ---
    (Rol.BIENESTAR, Recurso.PLAN): _W | {Accion.FIRMAR},
    (Rol.COORDINADOR, Recurso.PLAN): frozenset({L, Accion.VALIDAR, Accion.FIRMAR}),
    (Rol.DOCENTE, Recurso.PLAN): frozenset({L, Accion.ACEPTAR_RESPONSABILIDAD}),  # sus asignaturas
    (Rol.ESTUDIANTE, Recurso.PLAN): frozenset({L, Accion.CONCERTAR, Accion.FIRMAR}),
    (Rol.FAMILIAR, Recurso.PLAN): _R,
    # --- Seguimiento F8 ---
    (Rol.BIENESTAR, Recurso.SEGUIMIENTO): _W,
    (Rol.COORDINADOR, Recurso.SEGUIMIENTO): _R,
    (Rol.DOCENTE, Recurso.SEGUIMIENTO): frozenset({L, Accion.REGISTRAR_IMPLEMENTACION}),  # sus ajustes
    (Rol.ESTUDIANTE, Recurso.SEGUIMIENTO): frozenset({L, Accion.PERCEPCION}),
    (Rol.FAMILIAR, Recurso.SEGUIMIENTO): _R,
    # --- Evaluación F9 (docente y familiar no) ---
    (Rol.BIENESTAR, Recurso.EVALUACION): _W,
    (Rol.COORDINADOR, Recurso.EVALUACION): _R,
    (Rol.ESTUDIANTE, Recurso.EVALUACION): _R,
    # --- Notas de continuidad F10: Bienestar CRUD, Coordinador lectura, Estudiante lectura + aprobación ---
    (Rol.BIENESTAR, Recurso.NOTAS_CONTINUIDAD): _W,
    (Rol.COORDINADOR, Recurso.NOTAS_CONTINUIDAD): _R,
    (Rol.ESTUDIANTE, Recurso.NOTAS_CONTINUIDAD): frozenset({L, Accion.APROBAR}),
    # --- Trayectoria F10 ---
    (Rol.BIENESTAR, Recurso.TRAYECTORIA): _W,
    (Rol.COORDINADOR, Recurso.TRAYECTORIA): _R,
    (Rol.ESTUDIANTE, Recurso.TRAYECTORIA): _R,
    # --- No ligados a estudiante ---
    (Rol.ADMIN, Recurso.CATALOGO_DUA): _W,
    (Rol.BIENESTAR, Recurso.CATALOGO_DUA): _R,
    (Rol.COORDINADOR, Recurso.CATALOGO_DUA): _R,
    (Rol.DOCENTE, Recurso.CATALOGO_DUA): _R,
    (Rol.ADMIN, Recurso.AUDITORIA): _R,
}

#: Recurso -> alcance de la autorización familiar que lo habilita
_ALCANCE_FAMILIAR = {
    Recurso.CARACTERIZACION: AlcanceFamiliar.CARACTERIZACION,
    Recurso.PLAN: AlcanceFamiliar.PLAN,
    Recurso.SEGUIMIENTO: AlcanceFamiliar.SEGUIMIENTO,
}

#: Estados del plan visibles para el docente (no ve borradores ni planes en concertación)
PLAN_ESTADOS_VISIBLES_DOCENTE = (
    EstadoPlanEnum.APROBADO,
    EstadoPlanEnum.IMPLEMENTACION,
    EstadoPlanEnum.SEGUIMIENTO,
    EstadoPlanEnum.FINALIZADO,
)


# ============================================================================ consentimiento
def student_has_consent(db: Session, estudiante_id: int) -> bool:
    """True si el estudiante tiene un F0 FIRMADO vigente (no revocado)."""
    return db.scalar(
        select(
            exists().where(
                Consentimiento.estudiante_id == estudiante_id,
                Consentimiento.estado == EstadoConsentimiento.FIRMADO,
                Consentimiento.deleted_at.is_(None),
            )
        )
    ) or False


def user_has_consent(db: Session, user: Usuario) -> bool:
    """Para ESTUDIANTE: F0 firmado. Los demás roles no requieren F0."""
    if str(user.rol) != Rol.ESTUDIANTE:
        return True
    est_id = db.scalar(select(Estudiante.id).where(Estudiante.usuario_id == user.id))
    return bool(est_id) and student_has_consent(db, est_id)


# ============================================================================ alcance
def get_estudiante_or_404(db: Session, estudiante_id: int) -> Estudiante:
    est = db.get(Estudiante, estudiante_id)
    if est is None:
        raise NotFound("No encontramos al estudiante indicado.", "ESTUDIANTE_NO_ENCONTRADO")
    return est


def get_own_estudiante(db: Session, user: Usuario) -> Estudiante | None:
    return db.scalar(select(Estudiante).where(Estudiante.usuario_id == user.id))


def coordinador_programa_ids(db: Session, user: Usuario) -> set[int]:
    """Programas que coordina el usuario (lista en COORDINADOR_PROGRAMA + programas que lo nombran coordinador)."""
    from app.models.academico import ProgramaAcademico

    ids: set[int] = set()
    coord = db.scalar(select(CoordinadorPrograma).where(CoordinadorPrograma.usuario_id == user.id))
    if coord is None:
        return ids
    for v in coord.programa_responsable_ids or []:
        try:
            ids.add(int(v))
        except (TypeError, ValueError):
            continue
    ids.update(db.scalars(select(ProgramaAcademico.id).where(ProgramaAcademico.coordinador_programa_id == coord.id)))
    return ids


def docente_asignatura_ids_stmt(user: Usuario):
    return (
        select(AsignacionDocente.asignatura_id)
        .join(Docente, Docente.id == AsignacionDocente.docente_id)
        .where(Docente.usuario_id == user.id, AsignacionDocente.deleted_at.is_(None))
    )


def docente_plan_ids_stmt(user: Usuario):
    """Planes (en estado visible) que contienen ajustes o estrategias DUA de las asignaturas del docente
    o en los que figura como responsable."""
    asig = docente_asignatura_ids_stmt(user)
    ajuste_match = exists().where(
        AjusteRazonable.plan_id == PlanMaarTea.id,
        AjusteRazonable.deleted_at.is_(None),
        or_(AjusteRazonable.asignatura_id.in_(asig), AjusteRazonable.responsable_id == user.id),
    )
    dua_match = exists().where(
        EstrategiaDua.plan_id == PlanMaarTea.id,
        EstrategiaDua.deleted_at.is_(None),
        or_(EstrategiaDua.asignatura_id.in_(asig), EstrategiaDua.responsable_implementacion_id == user.id),
    )
    return select(PlanMaarTea.id).where(
        PlanMaarTea.deleted_at.is_(None),
        PlanMaarTea.estado.in_(PLAN_ESTADOS_VISIBLES_DOCENTE),
        or_(ajuste_match, dua_match),
    )


def docente_ajuste_ids(db: Session, user: Usuario, plan_id: int | None = None) -> set[int]:
    """Ajustes del plan que el docente puede ver (sus asignaturas o donde es responsable)."""
    asig = docente_asignatura_ids_stmt(user)
    stmt = select(AjusteRazonable.id).where(
        AjusteRazonable.deleted_at.is_(None),
        or_(AjusteRazonable.asignatura_id.in_(asig), AjusteRazonable.responsable_id == user.id),
    )
    if plan_id is not None:
        stmt = stmt.where(AjusteRazonable.plan_id == plan_id)
    else:
        stmt = stmt.where(AjusteRazonable.plan_id.in_(docente_plan_ids_stmt(user)))
    return set(db.scalars(stmt))


def familiar_autorizaciones_stmt(user: Usuario):
    now = utcnow()
    return select(AutorizacionFamiliar).where(
        AutorizacionFamiliar.familiar_usuario_id == user.id,
        AutorizacionFamiliar.deleted_at.is_(None),
        AutorizacionFamiliar.estado == EstadoAutorizacionFamiliar.VIGENTE,
        AutorizacionFamiliar.revocada_at.is_(None),
        or_(AutorizacionFamiliar.expira_at.is_(None), AutorizacionFamiliar.expira_at > now),
    )


def students_scope_criterion(user: Usuario):
    """Criterio SQLAlchemy sobre `Estudiante` con los estudiantes a los que el rol tiene alcance.

    Úselo para listados: ``select(Estudiante).where(students_scope_criterion(user))``.
    (Para COORDINADOR requiere `students_scope_criterion_db`, que conoce los programas.)
    """
    rol = str(user.rol)
    if rol == Rol.ADMIN:
        return Estudiante.id.is_not(None)
    if rol == Rol.BIENESTAR:
        if get_settings().bienestar_scope == "assigned":
            return or_(Estudiante.bienestar_asignado_id.is_(None), Estudiante.bienestar_asignado_id == user.id)
        return Estudiante.id.is_not(None)
    if rol == Rol.ESTUDIANTE:
        return Estudiante.usuario_id == user.id
    if rol == Rol.DOCENTE:
        return Estudiante.id.in_(
            select(PlanMaarTea.estudiante_id).where(PlanMaarTea.id.in_(docente_plan_ids_stmt(user)))
        )
    if rol == Rol.FAMILIAR:
        now = utcnow()
        return Estudiante.id.in_(
            select(AutorizacionFamiliar.estudiante_id).where(
                AutorizacionFamiliar.familiar_usuario_id == user.id,
                AutorizacionFamiliar.deleted_at.is_(None),
                AutorizacionFamiliar.estado == EstadoAutorizacionFamiliar.VIGENTE,
                AutorizacionFamiliar.revocada_at.is_(None),
                or_(AutorizacionFamiliar.expira_at.is_(None), AutorizacionFamiliar.expira_at > now),
            )
        )
    return Estudiante.id.is_(None)  # COORDINADOR u otros: ver students_scope_criterion_db


def students_scope_criterion_db(db: Session, user: Usuario):
    """Igual que `students_scope_criterion` pero resuelve también el alcance del COORDINADOR (su programa)."""
    if str(user.rol) == Rol.COORDINADOR:
        ids = coordinador_programa_ids(db, user)
        return Estudiante.programa_id.in_(ids) if ids else Estudiante.id.is_(None)
    return students_scope_criterion(user)


def can_access_student(db: Session, user: Usuario, estudiante_id: int) -> bool:
    """¿Está `user` vinculado a este estudiante (alcance)? No implica permiso sobre un recurso concreto."""
    est = db.get(Estudiante, estudiante_id)
    if est is None:
        return False
    rol = str(user.rol)
    if rol == Rol.ADMIN:
        return True
    if rol == Rol.ESTUDIANTE:
        return est.usuario_id == user.id
    if rol == Rol.BIENESTAR:
        if get_settings().bienestar_scope == "assigned":
            return est.bienestar_asignado_id in (None, user.id)
        return True
    if rol == Rol.COORDINADOR:
        return est.programa_id is not None and est.programa_id in coordinador_programa_ids(db, user)
    if rol == Rol.DOCENTE:
        return bool(
            db.scalar(
                select(
                    exists().where(PlanMaarTea.estudiante_id == estudiante_id, PlanMaarTea.id.in_(docente_plan_ids_stmt(user)))
                )
            )
        )
    if rol == Rol.FAMILIAR:
        return any(a.estudiante_id == estudiante_id for a in db.scalars(familiar_autorizaciones_stmt(user)))
    return False


def _familiar_permite(db: Session, user: Usuario, estudiante_id: int, recurso: Recurso) -> bool:
    alcance = _ALCANCE_FAMILIAR.get(recurso)
    if alcance is None:
        return False
    return any(
        a.estudiante_id == estudiante_id and a.permite(alcance) for a in db.scalars(familiar_autorizaciones_stmt(user))
    )


def acciones_permitidas(db: Session, user: Usuario, estudiante_id: int, recurso: Recurso) -> frozenset[Accion]:
    """Acciones que `user` puede ejecutar sobre `recurso` del estudiante (matriz ∩ alcance). Vacío = sin acceso."""
    base = MATRIZ.get((Rol(str(user.rol)), recurso), frozenset())
    if not base:
        return frozenset()
    if not can_access_student(db, user, estudiante_id):
        return frozenset()
    if str(user.rol) == Rol.FAMILIAR and not _familiar_permite(db, user, estudiante_id, recurso):
        return frozenset()
    return base


def can(db: Session, user: Usuario, estudiante_id: int, recurso: Recurso, accion: Accion = Accion.LEER) -> bool:
    return accion in acciones_permitidas(db, user, estudiante_id, recurso)


def can_view_clinical(db: Session, user: Usuario, estudiante_id: int) -> bool:
    """Datos clínicos/sensibles (F1, F2, diagnóstico). Docente NUNCA; Familiar solo con autorización de alcance."""
    return can(db, user, estudiante_id, Recurso.CARACTERIZACION, Accion.LEER)


def can_view_aq10(db: Session, user: Usuario, estudiante_id: int) -> bool:
    """Resultado AQ-10: solo Bienestar y el propio estudiante."""
    return can(db, user, estudiante_id, Recurso.AQ10, Accion.LEER)


def can_view_plan(db: Session, user: Usuario, estudiante_id: int) -> bool:
    return can(db, user, estudiante_id, Recurso.PLAN, Accion.LEER)


def can_write(db: Session, user: Usuario, estudiante_id: int, recurso: Recurso) -> bool:
    return can(db, user, estudiante_id, recurso, Accion.ESCRIBIR)


def assert_can(
    db: Session,
    user: Usuario,
    estudiante_id: int,
    recurso: Recurso,
    accion: Accion = Accion.LEER,
    *,
    require_consent: bool = True,
) -> Estudiante:
    """Valida alcance + matriz + F0 y devuelve el `Estudiante`. Lanza 404/403 con `code` claro."""
    est = get_estudiante_or_404(db, estudiante_id)
    if not can(db, user, estudiante_id, recurso, accion):
        raise Forbidden(
            "No tiene permiso para esta acción sobre este estudiante. Si cree que es un error, "
            "consulte con el equipo de Bienestar.",
            "ACCESO_DENEGADO",
        )
    if require_consent and recurso != Recurso.DATOS_BASICOS and not student_has_consent(db, estudiante_id):
        if str(user.rol) == Rol.ESTUDIANTE:
            raise ConsentRequired()
        raise Forbidden(
            "El estudiante aún no ha firmado el consentimiento informado (F0); no se pueden consultar ni "
            "registrar sus datos.",
            "ESTUDIANTE_SIN_CONSENTIMIENTO",
        )
    return est
