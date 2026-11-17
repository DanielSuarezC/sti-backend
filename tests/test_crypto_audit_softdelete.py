"""Cifrado en reposo, auditoría inmutable, soft delete y salvaguardas de modelos."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, StatementError

from app.core import audit
from app.core.crypto import DecryptionError, decrypt_str, encrypt_str
from app.models import (
    AuditoriaInmutableError,
    Base,
    Caracterizacion,
    Consentimiento,
    CuestionarioAQ10,
    DatoSensorial,
    EstadoPlan,
    Estudiante,
    HardDeleteForbidden,
    LogAuditoria,
    NotaContinuidad,
    PlanMaarTea,
    RespuestaAQ10,
    Usuario,
)
from app.models.base import utcnow
from app.models.consentimiento import ConsentimientoInmutableError
from app.models.enums import EstadoPlanEnum, ModalidadAQ10, Rol, TipoSensorial
from app.services.jobs import purge_unconsented_accounts
from tests.factories import make_estudiante, make_plan_with_ajuste, make_programa, make_user

SECRETO = "Narrativa clínica MUY sensible del estudiante"


# ------------------------------------------------------------------ cifrado
def test_aesgcm_roundtrip_and_randomized():
    a, b = encrypt_str("hola"), encrypt_str("hola")
    assert a != b and a.startswith("v1:")  # nonce aleatorio
    assert decrypt_str(a) == "hola"
    with pytest.raises(DecryptionError):
        decrypt_str(a[:-4] + "AAAA")  # alterado => falla autenticación GCM
    with pytest.raises(DecryptionError):
        decrypt_str("texto plano sin formato")


def test_encrypted_columns_not_plaintext_in_db(db):
    prog = make_programa(db)
    bienestar = make_user(db, Rol.BIENESTAR)
    eu, est = make_estudiante(db, prog)
    est.fecha_diagnostico_tea = date(2020, 5, 17)
    est.tipo_tea_caracterizacion = "TEA nivel 1 con apoyo"
    c = Caracterizacion(estudiante_id=est.id, fecha_caracterizacion=date.today(),
                        profesional_responsable_id=bienestar.id, resumen_ejecutivo=SECRETO,
                        autodescripcion_estudiante="Soy muy visual")
    db.add(c)
    db.flush()
    db.add(DatoSensorial(caracterizacion_id=c.id, tipo_sensorial=TipoSensorial.AUDITIVA,
                         descripcion_experiencia="Los timbres me duelen"))
    cuest = CuestionarioAQ10(nombre="AQ-10", version="1", items=[], opciones=[])
    db.add(cuest)
    db.flush()
    r = RespuestaAQ10(estudiante_id=est.id, cuestionario_id=cuest.id, aplicado_por_id=bienestar.id,
                      modalidad=ModalidadAQ10.ASISTIDA, aplicado_at=utcnow(), respuestas={"1": 1, "2": 4},
                      puntaje=7, punto_corte_aplicado=6, supera_umbral=True)
    db.add(r)
    n = NotaContinuidad(estudiante_id=est.id, semestre_origen="2026-II", contenido="Nota privada", elaborada_por_id=bienestar.id)
    db.add(n)
    db.commit()

    raw = {
        "caracterizacion": db.execute(text("SELECT resumen_ejecutivo, autodescripcion_estudiante FROM caracterizacion")).one(),
        "sensorial": db.execute(text("SELECT descripcion_experiencia FROM dato_sensorial")).one(),
        "aq10": db.execute(text("SELECT respuestas, puntaje FROM respuesta_aq10")).one(),
        "nota": db.execute(text("SELECT contenido FROM nota_continuidad")).one(),
        "est": db.execute(text("SELECT fecha_diagnostico_tea, tipo_tea_caracterizacion FROM estudiante WHERE id=:i"),
                          {"i": est.id}).one(),
    }
    for row in raw.values():
        for value in row:
            assert value.startswith("v1:"), value  # todo cifrado
    assert SECRETO not in str(raw) and "2020-05-17" not in str(raw) and "Los timbres" not in str(raw)

    # round-trip por el ORM
    db.expire_all()
    assert db.get(Caracterizacion, c.id).resumen_ejecutivo == SECRETO
    assert db.get(RespuestaAQ10, r.id).respuestas == {"1": 1, "2": 4}
    assert db.get(RespuestaAQ10, r.id).puntaje == 7
    assert db.get(Estudiante, est.id).fecha_diagnostico_tea == date(2020, 5, 17)


def test_production_requires_encryption_key(monkeypatch):
    from app.core import config, crypto, devsecrets

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "")
    config.reset_settings_cache()
    crypto.reset_crypto_cache()
    try:
        with pytest.raises(devsecrets.ConfigError) as ei:
            crypto.validate_key()
        assert "DATA_ENCRYPTION_KEY" in str(ei.value)
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        config.reset_settings_cache()
        crypto.reset_crypto_cache()


# ------------------------------------------------------------------ auditoría inmutable
def test_audit_append_only(db):
    u = make_user(db, Rol.BIENESTAR)
    e = audit.log(db, u, "ACCESO_AQ10", "respuesta_aq10", 5, {"password": "x", "puntaje": 9, "ok": 1}, estudiante_id=3)
    db.commit()
    assert e.id and e.actor_rol == "BIENESTAR" and e.detalle == {"password": "***", "puntaje": "***", "ok": 1}

    e.accion = "OTRA"
    with pytest.raises(AuditoriaInmutableError):
        db.commit()
    db.rollback()
    db.delete(db.get(LogAuditoria, e.id))
    with pytest.raises(AuditoriaInmutableError):
        db.commit()
    db.rollback()
    with pytest.raises(AuditoriaInmutableError):
        db.execute(update(LogAuditoria).values(accion="X"))
    from sqlalchemy import delete

    with pytest.raises(AuditoriaInmutableError):
        db.execute(delete(LogAuditoria))
    assert db.scalar(select(LogAuditoria.accion).where(LogAuditoria.id == e.id)) == "ACCESO_AQ10"


# ------------------------------------------------------------------ consentimiento inmutable
def test_consentimiento_firmado_inmutable_salvo_revocacion(db):
    prog = make_programa(db)
    eu, est = make_estudiante(db, prog)
    c = db.scalar(select(Consentimiento).where(Consentimiento.estudiante_id == est.id))
    c.texto_hash = "f" * 64
    with pytest.raises(ConsentimientoInmutableError):
        db.commit()
    db.rollback()
    c = db.scalar(select(Consentimiento).where(Consentimiento.estudiante_id == est.id))
    c.estado = "REVOCADO"
    c.revocado_at = utcnow()
    db.commit()  # la revocación sí se permite


# ------------------------------------------------------------------ soft delete
def test_soft_delete_hides_and_include_deleted(db):
    prog = make_programa(db)
    eu, est = make_estudiante(db, prog)
    bienestar = make_user(db, Rol.BIENESTAR)
    plan, ajuste = make_plan_with_ajuste(db, est, bienestar)
    ajuste.soft_delete(bienestar.id, "creado por error")
    db.commit()
    from app.models import AjusteRazonable

    assert db.scalar(select(AjusteRazonable).where(AjusteRazonable.id == ajuste.id)) is None
    vis = db.scalar(select(AjusteRazonable).where(AjusteRazonable.id == ajuste.id).execution_options(include_deleted=True))
    assert vis is not None and vis.deleted_reason == "creado por error" and vis.deleted_by_id == bienestar.id
    db.expire_all()
    assert db.get(PlanMaarTea, plan.id).ajustes == []  # relaciones también filtran
    vis.restore()
    db.commit()
    assert db.scalar(select(AjusteRazonable).where(AjusteRazonable.id == ajuste.id)) is not None


def test_physical_delete_forbidden_except_estado_plan(db):
    prog = make_programa(db)
    db.delete(prog)
    with pytest.raises(HardDeleteForbidden):
        db.commit()
    db.rollback()
    ep = EstadoPlan(nombre_estado="TEMP")
    db.add(ep)
    db.commit()
    db.delete(ep)
    db.commit()  # catálogo ESTADO_PLAN: DELETE físico permitido
    assert db.scalar(select(EstadoPlan).where(EstadoPlan.nombre_estado == "TEMP")) is None


def test_one_active_plan_per_student_semester(db):
    prog = make_programa(db)
    eu, est = make_estudiante(db, prog)
    bienestar = make_user(db, Rol.BIENESTAR)
    plan, _ = make_plan_with_ajuste(db, est, bienestar)
    dup = PlanMaarTea(estudiante_id=est.id, fecha_elaboracion=date.today(), semestre_academico="2026-II",
                      vigencia_inicio=date.today(), estado=EstadoPlanEnum.BORRADOR)
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    plan = db.get(PlanMaarTea, plan.id)
    plan.estado = EstadoPlanEnum.ARCHIVADO
    db.commit()
    db.add(PlanMaarTea(estudiante_id=est.id, fecha_elaboracion=date.today(), semestre_academico="2026-II",
                       vigencia_inicio=date.today(), estado=EstadoPlanEnum.BORRADOR))
    db.commit()  # con el anterior archivado, se permite uno nuevo


def test_check_constraints(db):
    prog = make_programa(db)
    eu, est = make_estudiante(db, prog)
    bad = PlanMaarTea(estudiante_id=est.id, fecha_elaboracion=date.today(), semestre_academico="2026-I",
                      vigencia_inicio=date.today(), vigencia_fin=date.today() - timedelta(days=1))
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    with pytest.raises(StatementError):  # enum inválido rechazado por validate_strings
        db.add(Usuario(email="x@example.com", nombre_completo="x", rol="SUPERUSUARIO"))
        db.flush()
    db.rollback()


def test_purge_unconsented_accounts_after_30_days(db):
    prog = make_programa(db)
    viejo, est_v = make_estudiante(db, prog, consent=False)
    reciente, est_r = make_estudiante(db, prog, consent=False)
    firmado, est_f = make_estudiante(db, prog, consent=True)
    viejo.created_at = utcnow() - timedelta(days=31)
    db.commit()
    n = purge_unconsented_accounts(db, date.today())
    db.commit()
    assert n == 1
    assert db.get(Usuario, viejo.id) is None and db.get(Usuario, reciente.id) is not None
    assert db.get(Usuario, firmado.id) is not None
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "PURGA_CUENTAS_SIN_CONSENTIMIENTO"))


# ------------------------------------------------------------------ modelo
def test_model_inventory():
    names = set(Base.metadata.tables)
    erd_69 = """usuario estudiante caracterizacion dato_comunicacion dato_autonomia dato_sensorial dato_preferencia
    perfil_fortalezas fortaleza interes estrategia_aprendizaje contexto_universitario contexto_aula contexto_docente
    contexto_evaluacion contexto_campus barrera_identificada barrera_actitudinal barrera_comunicativa barrera_pedagogica
    barrera_evaluativa barrera_sensorial barrera_social barrera_institucional barrera_tecnologica facilitador
    facilitador_personal facilitador_pedagogico facilitador_social facilitador_institucional facilitador_tecnologico
    plan_maar_tea estrategia_dua ajuste_razonable respuesta_comunicacion respuesta_pedagogia respuesta_evaluacion
    respuesta_ambiente respuesta_interaccion respuesta_tecnologia apoyo tipo_apoyo responsable_apoyo recurso
    implementacion_apoyo registro_implementacion seguimiento registro_seguimiento evidencia_efectividad
    resultado_indicador evaluacion_plan decision_plan estado_plan trayectoria_academica acceso participacion
    aprendizaje bienestar autonomia permanencia progresion graduacion transicion_profesional matricula
    programa_academico docente coordinador_programa personal_administrativo personal_bienestar""".split()
    assert len(erd_69) == 69
    assert set(erd_69) <= names
    for extra in ("consentimiento cuestionario_aq10 respuesta_aq10 tarea_negociacion log_auditoria estrategia_dua_catalogo "
                  "sugerencia_dua caso_cbr calendario_academico parametro_sistema notificacion email_outbox "
                  "autorizacion_familiar firma_plan plan_version registro_seguimiento_ajuste asignatura "
                  "asignacion_docente solicitud_ingreso nota_continuidad preferencia_sensorial_ui refresh_token "
                  "exportacion contexto_virtualidad contexto_laboratorio contexto_practica_clinica "
                  "contexto_practica_salud_publica contexto_evento contexto_pasantia").split():
        assert extra in names, extra
    assert len(names) >= 100
    # nombres de constraint válidos para PostgreSQL (<= 63)
    for t in Base.metadata.tables.values():
        for c in t.constraints:
            assert c.name is None or len(c.name) <= 63, c.name
    # todas las tablas de negocio llevan id + timestamps (+ soft delete salvo log_auditoria/refresh_token)
    for name, t in Base.metadata.tables.items():
        assert "id" in t.c, name
        assert "created_at" in t.c, name
        if name not in ("log_auditoria", "refresh_token"):
            assert {"updated_at", "deleted_at", "deleted_reason", "deleted_by_id"} <= set(t.c.keys()), name
