"""Matriz §12.1, alcance por objeto y gate de consentimiento F0."""

from __future__ import annotations

from datetime import timedelta

from app.core.permissions import (
    Accion,
    Recurso,
    can,
    can_access_student,
    can_view_aq10,
    can_view_clinical,
    can_view_plan,
    can_write,
    docente_ajuste_ids,
    students_scope_criterion,
    students_scope_criterion_db,
)
from app.models import Estudiante
from app.models.base import utcnow
from app.models.enums import EstadoPlanEnum, Rol
from tests.factories import (
    auth_headers,
    authorize_familiar,
    make_estudiante,
    make_plan_with_ajuste,
    make_user,
)


def _get(client, user, est_id, recurso, accion="LEER"):
    return client.get(f"/_t/estudiantes/{est_id}/{recurso}", params={"accion": accion}, headers=auth_headers(user))


# ------------------------------------------------------------------ AQ-10 y F1: docente NO; estudiante solo lo propio
def test_aq10_matrix(db, world):
    w = world
    est = w.estudiante.id
    assert can_view_aq10(db, w.bienestar, est)
    assert can_view_aq10(db, w.estudiante_user, est)
    assert not can_view_aq10(db, w.otro_estudiante_user, est)  # otro estudiante: no
    assert not can_view_aq10(db, w.docente, est)
    assert not can_view_aq10(db, w.coordinador, est)  # coordinador: No
    assert not can_view_aq10(db, w.admin, est)  # admin: solo configura
    assert not can_view_aq10(db, w.familiar, est)


def test_clinical_f1_f2_matrix(db, world):
    w = world
    est = w.estudiante.id
    assert can_view_clinical(db, w.bienestar, est) and can_write(db, w.bienestar, est, Recurso.CARACTERIZACION)
    assert can_view_clinical(db, w.coordinador, est) and not can_write(db, w.coordinador, est, Recurso.CARACTERIZACION)
    assert can_view_clinical(db, w.estudiante_user, est)
    assert not can_view_clinical(db, w.otro_estudiante_user, est)
    assert not can_view_clinical(db, w.docente, est)
    assert not can_view_clinical(db, w.admin, est)
    assert not can_view_clinical(db, w.familiar, est)  # sin autorización


def test_docente_never_sees_clinical_even_with_plan(db, world):
    w = world
    plan, ajuste = make_plan_with_ajuste(db, w.estudiante, w.bienestar, asignatura=w.asignatura)
    est = w.estudiante.id
    assert can_access_student(db, w.docente, est)  # tiene plan visible en su asignatura
    assert can_view_plan(db, w.docente, est)
    for recurso in (Recurso.AQ10, Recurso.CARACTERIZACION, Recurso.BARRERAS, Recurso.FACILITADORES,
                    Recurso.NOTAS_CONTINUIDAD, Recurso.EVALUACION, Recurso.CONTEXTO, Recurso.TRAYECTORIA):
        assert not can(db, w.docente, est, recurso), recurso
    assert can(db, w.docente, est, Recurso.SEGUIMIENTO, Accion.REGISTRAR_IMPLEMENTACION)
    assert not can(db, w.docente, est, Recurso.PLAN, Accion.ESCRIBIR)
    assert docente_ajuste_ids(db, w.docente, plan.id) == {ajuste.id}
    # otro docente sin asignaturas ni responsabilidad: ni siquiera alcanza al estudiante
    assert not can_access_student(db, w.docente_otro, est)
    assert not can_view_plan(db, w.docente_otro, est)


def test_docente_does_not_see_draft_plans(db, world):
    w = world
    make_plan_with_ajuste(db, w.estudiante, w.bienestar, asignatura=w.asignatura, estado=EstadoPlanEnum.BORRADOR)
    assert not can_access_student(db, w.docente, w.estudiante.id)
    assert not can_view_plan(db, w.docente, w.estudiante.id)


def test_student_only_own_data(db, world, client):
    w = world
    assert can(db, w.estudiante_user, w.estudiante.id, Recurso.PLAN)
    assert not can(db, w.estudiante_user, w.otro_estudiante.id, Recurso.PLAN)
    assert _get(client, w.estudiante_user, w.estudiante.id, "AQ10").status_code == 200
    r = _get(client, w.estudiante_user, w.otro_estudiante.id, "AQ10")
    assert r.status_code == 403 and r.json()["code"] == "ACCESO_DENEGADO"
    # el estudiante no puede escribir caracterización clínica (solo aportar su voz)
    assert _get(client, w.estudiante_user, w.estudiante.id, "CARACTERIZACION", "ESCRIBIR").status_code == 403
    assert _get(client, w.estudiante_user, w.estudiante.id, "CARACTERIZACION", "APORTAR").status_code == 200
    assert _get(client, w.estudiante_user, w.estudiante.id, "PLAN", "CONCERTAR").status_code == 200
    assert _get(client, w.estudiante_user, w.estudiante.id, "NOTAS_CONTINUIDAD", "APROBAR").status_code == 200


def test_familiar_only_with_student_authorization(db, world, client):
    w = world
    est = w.estudiante.id
    assert not can_access_student(db, w.familiar, est)
    assert _get(client, w.familiar, est, "PLAN").status_code == 403
    a = authorize_familiar(db, w.estudiante, w.familiar, ["PLAN", "SEGUIMIENTO"])
    assert can(db, w.familiar, est, Recurso.PLAN) and can(db, w.familiar, est, Recurso.SEGUIMIENTO)
    assert not can(db, w.familiar, est, Recurso.CARACTERIZACION)  # fuera del alcance autorizado
    assert not can(db, w.familiar, est, Recurso.AQ10) and not can(db, w.familiar, est, Recurso.BARRERAS)
    assert not can(db, w.familiar, est, Recurso.PLAN, Accion.ESCRIBIR)  # solo lectura
    assert _get(client, w.familiar, est, "PLAN").status_code == 200
    assert not can_access_student(db, w.familiar, w.otro_estudiante.id)
    # ampliar alcance a F1
    a.alcance = ["PLAN", "SEGUIMIENTO", "CARACTERIZACION"]
    db.commit()
    assert can_view_clinical(db, w.familiar, est)
    # revocar
    a.estado = "REVOCADA"
    a.revocada_at = utcnow()
    db.commit()
    assert not can(db, w.familiar, est, Recurso.PLAN) and not can_access_student(db, w.familiar, est)
    assert _get(client, w.familiar, est, "PLAN").status_code == 403


def test_familiar_authorization_expires(db, world):
    w = world
    a = authorize_familiar(db, w.estudiante, w.familiar, ["PLAN"])
    a.expira_at = utcnow() - timedelta(days=1)
    db.commit()
    assert not can(db, w.familiar, w.estudiante.id, Recurso.PLAN)


def test_coordinador_only_own_program(db, world):
    w = world
    est = w.estudiante.id
    assert can_access_student(db, w.coordinador, est)
    assert not can_access_student(db, w.coordinador_otro, est)
    assert can(db, w.coordinador, est, Recurso.PLAN, Accion.VALIDAR)
    assert can(db, w.coordinador, est, Recurso.PLAN, Accion.FIRMAR)
    assert not can(db, w.coordinador, est, Recurso.PLAN, Accion.ESCRIBIR)  # lectura + validación
    assert not can(db, w.coordinador_otro, est, Recurso.PLAN)
    assert can(db, w.coordinador, est, Recurso.SEGUIMIENTO) and can(db, w.coordinador, est, Recurso.NOTAS_CONTINUIDAD)
    assert not can(db, w.coordinador, est, Recurso.NOTAS_CONTINUIDAD, Accion.ESCRIBIR)


def test_admin_has_no_clinical_access(db, world):
    w = world
    est = w.estudiante.id
    for r in (Recurso.AQ10, Recurso.CARACTERIZACION, Recurso.BARRERAS, Recurso.PLAN, Recurso.SEGUIMIENTO,
              Recurso.NOTAS_CONTINUIDAD):
        assert not can(db, w.admin, est, r), r
    assert can(db, w.admin, est, Recurso.DATOS_BASICOS)


def test_bienestar_full_crud_on_students(db, world):
    w = world
    for r in (Recurso.CARACTERIZACION, Recurso.BARRERAS, Recurso.PLAN, Recurso.SEGUIMIENTO, Recurso.NOTAS_CONTINUIDAD):
        assert can(db, w.bienestar, w.estudiante.id, r, Accion.ESCRIBIR), r


def test_scope_criterion_for_listings(db, world):
    from sqlalchemy import select

    w = world

    def ids(user, with_db=False):
        crit = students_scope_criterion_db(db, user) if with_db else students_scope_criterion(user)
        return set(db.scalars(select(Estudiante.id).where(crit)))

    assert ids(w.estudiante_user) == {w.estudiante.id}
    assert ids(w.bienestar) == {w.estudiante.id, w.otro_estudiante.id}
    assert ids(w.coordinador, True) == {w.estudiante.id, w.otro_estudiante.id}
    assert ids(w.coordinador_otro, True) == set()
    assert ids(w.docente) == set() and ids(w.familiar) == set()
    make_plan_with_ajuste(db, w.estudiante, w.bienestar, asignatura=w.asignatura)
    assert ids(w.docente) == {w.estudiante.id}
    authorize_familiar(db, w.otro_estudiante, w.familiar, ["PLAN"])
    assert ids(w.familiar) == {w.otro_estudiante.id}


def test_bienestar_assigned_scope(db, world, monkeypatch):
    from app.core import config

    w = world
    otro_bienestar = make_user(db, Rol.BIENESTAR)
    w.estudiante.bienestar_asignado_id = otro_bienestar.id
    db.commit()
    monkeypatch.setenv("BIENESTAR_SCOPE", "assigned")
    config.reset_settings_cache()
    try:
        assert not can_access_student(db, w.bienestar, w.estudiante.id)
        assert can_access_student(db, otro_bienestar, w.estudiante.id)
        assert can_access_student(db, w.bienestar, w.otro_estudiante.id)  # sin asignar: todos
    finally:
        monkeypatch.setenv("BIENESTAR_SCOPE", "all")
        config.reset_settings_cache()


# ------------------------------------------------------------------ gate de consentimiento
def test_student_without_f0_gets_403_consent_required(db, world, client):
    w = world
    sin_f0_user, sin_f0 = make_estudiante(db, w.programa, consent=False)
    r = client.get("/_t/propio", headers=auth_headers(sin_f0_user))
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
    assert "consentimiento" in r.json()["detail"].lower()
    r = client.get("/_t/bienestar-consent", headers=auth_headers(sin_f0_user))
    assert r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
    # acceso a datos propios (assert_can) también bloqueado
    r = _get(client, sin_f0_user, sin_f0.id, "PLAN")
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
    # con F0 firmado pasa
    assert client.get("/_t/propio", headers=auth_headers(w.estudiante_user)).status_code == 200


def test_staff_cannot_read_student_data_before_f0(db, world, client):
    w = world
    _, sin_f0 = make_estudiante(db, w.programa, consent=False)
    r = _get(client, w.bienestar, sin_f0.id, "CARACTERIZACION")
    assert r.status_code == 403 and r.json()["code"] == "ESTUDIANTE_SIN_CONSENTIMIENTO"
    assert _get(client, w.bienestar, sin_f0.id, "DATOS_BASICOS").status_code == 200  # datos mínimos sí (alta/pendientes)


def test_non_students_not_gated_and_role_guard(db, world, client):
    w = world
    assert client.get("/_t/propio", headers=auth_headers(w.bienestar)).status_code == 200
    r = client.get("/_t/solo-admin", headers=auth_headers(w.bienestar))
    assert r.status_code == 403 and r.json()["code"] == "ROL_NO_PERMITIDO"
    assert client.get("/_t/solo-admin", headers=auth_headers(w.admin)).status_code == 200
    assert client.get("/_t/solo-admin").status_code == 401


def test_revoked_consent_blocks_again(db, world, client):
    from sqlalchemy import select

    from app.models import Consentimiento

    w = world
    c = db.scalar(select(Consentimiento).where(Consentimiento.estudiante_id == w.estudiante.id))
    c.estado = "REVOCADO"
    c.revocado_at = utcnow()
    db.commit()
    r = client.get("/_t/propio", headers=auth_headers(w.estudiante_user))
    assert r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"


def test_unknown_student_404(db, world, client):
    r = _get(client, world.bienestar, 9999, "PLAN")
    assert r.status_code == 404 and r.json()["code"] == "ESTUDIANTE_NO_ENCONTRADO"
