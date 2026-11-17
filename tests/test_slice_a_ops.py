"""Slice A: salud, auditoría, jobs diarios, cola de correo y notificaciones."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.core import audit
from app.core.config import get_settings
from app.models import (
    AutorizacionFamiliar,
    EmailOutbox,
    LogAuditoria,
    Notificacion,
    PlanMaarTea,
    Usuario,
)
from app.models.base import utcnow
from app.models.enums import (
    EstadoAutorizacionFamiliar,
    EstadoEmail,
    EstadoPlanEnum,
    EstadoUsuario,
    Rol,
)
from app.services import jobs
from app.services.notifications import Evento, notify
from tests._slice_a_helpers import make_calendar
from tests.factories import authorize_familiar, make_estudiante, make_plan_with_ajuste, make_user

API = "/api/v1"
HOY = date(2026, 10, 1)


# ----------------------------------------------------------------------------- salud y auditoría
def test_salud_solo_admin_y_contenido(client, db, world, auth):
    db.add(EmailOutbox(destinatario_email="x@example.com", asunto="a", cuerpo_texto="b", estado=EstadoEmail.ERROR, intentos=5,
                       ultimo_error="SMTP caído"))
    db.add(EmailOutbox(destinatario_email="y@example.com", asunto="a", cuerpo_texto="b", estado=EstadoEmail.PENDIENTE))
    db.commit()
    for u in (world.bienestar, world.coordinador, world.docente, world.estudiante_user):
        assert client.get(f"{API}/admin/salud", headers=auth(u)).status_code == 403
    j = client.get(f"{API}/admin/salud", headers=auth(world.admin)).json()
    assert j["base_de_datos"]["ok"] is True and j["version"] and j["status"] == "degradado"  # hay un correo fallido
    assert j["cola_email"]["pendientes"] == 1 and j["cola_email"]["fallidas"] == 1
    assert j["cola_email"]["ultimos_errores"][0]["error"] == "SMTP caído"
    assert j["tareas"]["modo"] == "en_linea" and j["conteos"]["usuarios_activos"] >= 8
    assert isinstance(j["ultimos_errores"], list)


def test_auditoria_filtros_paginacion_y_sin_datos_sensibles(client, db, world, auth):
    audit.log(db, world.bienestar, "ACCESO_AQ10", "respuesta_aq10", 5, {"puntaje": 8, "respuestas": {"1": 1}, "modalidad": "ASISTIDA"},
              estudiante_id=world.estudiante.id, commit=True)
    audit.log(db, world.admin, "OTRA_ACCION", "usuario", 1, {"cuerpo": "texto privado largo"}, commit=True)
    h = auth(world.admin)
    for u in (world.bienestar, world.coordinador, world.docente, world.estudiante_user):
        assert client.get(f"{API}/admin/auditoria", headers=auth(u)).status_code == 403
    r = client.get(f"{API}/admin/auditoria?accion=ACCESO_AQ10", headers=h).json()
    assert r["total"] == 1
    d = r["items"][0]["detalle"]
    assert d["puntaje"] == "***" and d["respuestas"] == "***" and d["modalidad"] == "ASISTIDA"
    assert "texto privado" not in client.get(f"{API}/admin/auditoria?accion=OTRA_ACCION", headers=h).text
    assert client.get(f"{API}/admin/auditoria?actor_id={world.bienestar.id}", headers=h).json()["total"] == 1
    assert client.get(f"{API}/admin/auditoria?entidad=usuario&entidad_id=1", headers=h).json()["total"] == 1
    hoy = utcnow().date().isoformat()
    assert client.get(f"{API}/admin/auditoria?desde={hoy}&hasta={hoy}", headers=h).json()["total"] >= 2
    assert client.get(f"{API}/admin/auditoria?desde=2020-01-01&hasta=2020-01-02", headers=h).json()["total"] == 0
    pag = client.get(f"{API}/admin/auditoria?page=1&page_size=1", headers=h).json()
    assert len(pag["items"]) == 1 and pag["total"] >= 3
    assert "ACCESO_AQ10" in client.get(f"{API}/admin/auditoria/acciones", headers=h).json()["items"]
    # consultar la auditoría también queda auditado
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "ACCESO_AUDITORIA"))


# ----------------------------------------------------------------------------- endpoint de jobs
def test_jobs_run_daily_autorizacion(client, db, world, auth, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "jobs_secret", "s3cr3to-largo")
    assert client.post(f"{API}/admin/jobs/run-daily").status_code == 401
    assert client.post(f"{API}/admin/jobs/run-daily", headers={"X-Jobs-Secret": "equivocado"}).json()["code"] == "JOBS_SECRET_INVALIDO"
    ok = client.post(f"{API}/admin/jobs/run-daily?hoy=2026-10-01", headers={"X-Jobs-Secret": "s3cr3to-largo"})
    assert ok.status_code == 200
    j = ok.json()
    assert j["origen"] == "secreto" and j["hoy"] == "2026-10-01" and j["errores"] == 0
    assert {"recordatorios_corte", "inicio_semestre_f3", "semestre_practicas", "vencimiento_invitaciones", "purga_sin_consentimiento",
            "negociaciones_estancadas"} <= set(j["resultados"])
    assert client.post(f"{API}/admin/jobs/run-daily", headers=auth(world.admin)).status_code == 200
    assert client.post(f"{API}/admin/jobs/run-daily", headers=auth(world.bienestar)).status_code == 403
    db.expire_all()
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "JOBS_DIARIOS_EJECUTADOS"))
    monkeypatch.setattr(s, "jobs_secret", "")
    assert client.post(f"{API}/admin/jobs/run-daily", headers={"X-Jobs-Secret": ""}).status_code == 401  # sin secreto configurado: deshabilitado


def test_outbox_reintentar(client, db, world, auth):
    for i in range(2):
        db.add(EmailOutbox(destinatario_email=f"e{i}@example.com", asunto="a", cuerpo_texto="b", estado=EstadoEmail.ERROR, intentos=5, ultimo_error="x"))
    db.commit()
    assert client.post(f"{API}/admin/email-outbox/reintentar", headers=auth(world.bienestar)).status_code == 403
    r = client.post(f"{API}/admin/email-outbox/reintentar", headers=auth(world.admin))
    assert r.status_code == 200 and r.json()["reintentados"] == 2 and r.json()["smtp_configurado"] is False and r.json()["omitidos"] == 2
    db.expire_all()
    assert all(e.estado == EstadoEmail.OMITIDO and e.ultimo_error is None for e in db.scalars(select(EmailOutbox)))
    assert client.post(f"{API}/admin/email-outbox/reintentar", headers=auth(world.admin)).json()["reintentados"] == 0
    assert client.get(f"{API}/notificaciones/outbox?estado=OMITIDO", headers=auth(world.admin)).json()["total"] == 2


# ----------------------------------------------------------------------------- jobs (servicio)
def _plan_vigente(db, world, estado=EstadoPlanEnum.IMPLEMENTACION):
    return make_plan_with_ajuste(db, world.estudiante, world.bienestar, asignatura=world.asignatura, estado=estado)


def _por_evento(db, evento):
    db.expire_all()
    return list(db.scalars(select(EmailOutbox).where(EmailOutbox.evento == evento)))


def test_recordatorio_corte_7_dias_correo_idempotente(db, world):
    cal = make_calendar(db, hoy=HOY, c1=HOY + timedelta(days=7))
    _plan_vigente(db, world)
    n = jobs.send_cut_reminders(db, HOY)
    db.commit()
    assert n["afectados"] == 3 and n["C1_7d"] == 3  # Bienestar + Estudiante + Docente responsable
    filas = _por_evento(db, "RECORDATORIO_CORTE_7D")
    assert {f.usuario_id for f in filas} == {world.bienestar.id, world.estudiante_user.id, world.docente.id}
    assert all("C1" in f.asunto for f in filas)
    assert not db.scalars(select(Notificacion).where(Notificacion.tipo == "RECORDATORIO_CORTE_7D")).all()  # 7 d = solo correo
    assert jobs.send_cut_reminders(db, HOY)["afectados"] == 0  # idempotente
    db.commit()
    assert len(_por_evento(db, "RECORDATORIO_CORTE_7D")) == 3
    assert cal.id


def test_recordatorio_corte_1_dia_push_y_sin_plan(db, world):
    make_calendar(db, hoy=HOY, c2=HOY + timedelta(days=1))
    # sin plan vigente: solo Bienestar
    n = jobs.send_cut_reminders(db, HOY)
    db.commit()
    assert n["afectados"] == 1
    _plan_vigente(db, world)
    n2 = jobs.send_cut_reminders(db, HOY)
    db.commit()
    assert n2["afectados"] == 2  # estudiante y docente; Bienestar ya había recibido
    push = db.scalars(select(Notificacion).where(Notificacion.tipo == "RECORDATORIO_CORTE_1D")).all()
    assert {p.usuario_id for p in push} == {world.bienestar.id, world.estudiante_user.id, world.docente.id}
    assert all("C2" in p.titulo for p in push)
    assert jobs.send_cut_reminders(db, HOY + timedelta(days=3))["afectados"] == 0  # fuera de ventana


def test_recordatorio_respeta_calendario_por_programa_y_estados(db, world):
    make_calendar(db, hoy=HOY, programa_id=world.otro_programa.id, c1=HOY + timedelta(days=7))
    _plan_vigente(db, world, estado=EstadoPlanEnum.BORRADOR)
    n = jobs.send_cut_reminders(db, HOY)
    assert n["afectados"] == 1  # el estudiante es de otro programa y su plan es borrador: solo Bienestar


def test_inicio_semestre_f3_pendiente(db, world):
    make_calendar(db, hoy=HOY, offset_inicio=0)
    r = jobs.start_of_semester_f3_pending(db, HOY)
    db.commit()
    assert r["afectados"] == 1 and r["estudiantes_pendientes"] == 2  # los 2 estudiantes del mundo con F0
    assert len(_por_evento(db, "INICIO_SEMESTRE_F3_PENDIENTE")) == 1
    assert jobs.start_of_semester_f3_pending(db, HOY)["afectados"] == 0
    assert jobs.start_of_semester_f3_pending(db, HOY + timedelta(days=60))["afectados"] == 0  # fuera de ventana


def test_alerta_semestre_de_practicas(db, world):
    world.programa.semestre_practicas = 7
    world.estudiante.semestre_actual = 7
    db.commit()
    make_calendar(db, hoy=HOY, fecha_inicio_practicas=HOY)
    assert jobs.practice_semester_alert(db, HOY - timedelta(days=1))["afectados"] == 0  # aún no empiezan prácticas
    r = jobs.practice_semester_alert(db, HOY)
    db.commit()
    assert r["afectados"] == 1
    fila = _por_evento(db, "SEMESTRE_PRACTICAS")[0]
    assert fila.usuario_id == world.bienestar.id
    assert jobs.practice_semester_alert(db, HOY + timedelta(days=1))["afectados"] == 0  # una sola vez por semestre


def test_invitaciones_vencidas(db, world):
    pend = make_user(db, Rol.DOCENTE, estado=EstadoUsuario.PENDIENTE_ACTIVACION, password=None)
    pend.activation_token_hash = "abc"
    pend.activation_expires_at = utcnow() - timedelta(hours=1)
    vigente = make_user(db, Rol.DOCENTE, estado=EstadoUsuario.PENDIENTE_ACTIVACION, password=None)
    vigente.activation_token_hash = "def"
    vigente.activation_expires_at = utcnow() + timedelta(hours=10)
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    a.expira_at = utcnow() - timedelta(days=1)
    db.commit()
    r = jobs.expire_invitations(db, HOY)
    db.commit()
    assert r["invitaciones_otros"] == 1 and r["autorizaciones_expiradas"] == 1
    db.expire_all()
    assert db.get(Usuario, pend.id).activation_token_hash is None and db.get(Usuario, vigente.id).activation_token_hash == "def"
    assert db.get(AutorizacionFamiliar, a.id).estado == EstadoAutorizacionFamiliar.EXPIRADA
    avisos = db.scalars(select(Notificacion).where(Notificacion.tipo == "INVITACION_VENCIDA")).all()
    assert [x.usuario_id for x in avisos] == [world.admin.id]
    assert jobs.expire_invitations(db, HOY)["afectados"] == 0


def test_negociaciones_estancadas(db, world):
    plan, _ = _plan_vigente(db, world, estado=EstadoPlanEnum.EN_NEGOCIACION)
    assert jobs.stalled_negotiations(db, HOY)["planes"] == 0  # recién tocado
    plan.updated_at = utcnow() - timedelta(days=10)
    db.commit()
    r = jobs.stalled_negotiations(db, HOY)
    db.commit()
    assert r["planes"] == 1 and r["afectados"] == 1
    assert jobs.stalled_negotiations(db, HOY)["afectados"] == 0  # un recordatorio por semana
    assert jobs.stalled_negotiations(db, HOY + timedelta(days=7))["afectados"] == 1
    n = db.scalar(select(Notificacion).where(Notificacion.tipo == "NEGOCIACION_ESTANCADA"))
    assert n.enlace == f"/bienestar/planes/{plan.id}"


def test_purga_30_dias_y_run_daily_con_aislamiento_de_errores(db, world, monkeypatch):
    viejo_u, _ = make_estudiante(db, world.programa, consent=False)
    viejo_u.created_at = utcnow() - timedelta(days=31)
    nuevo_u, _ = make_estudiante(db, world.programa, consent=False)
    db.commit()

    def roto(db_, hoy_):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(jobs, "JOBS", [("roto", roto)] + list(jobs.JOBS))
    res = jobs.run_daily_jobs(db, HOY)
    assert res["roto"]["error"] == "falla simulada"
    assert res["purga_sin_consentimiento"]["afectados"] == 1  # el error de un job no tumba a los demás
    db.expire_all()
    assert db.get(Usuario, viejo_u.id) is None and db.get(Usuario, nuevo_u.id) is not None
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "PURGA_CUENTAS_SIN_CONSENTIMIENTO"))
    assert db.scalar(select(PlanMaarTea.id)) is None  # no se tocó nada pedagógico


# ----------------------------------------------------------------------------- notificaciones
def _crear_notifs(db, user, n=3):
    notify(db, Evento.PLAN_LISTO_FIRMA, [user], {"version": 1, "enlace": "/estudiante/plan"})
    for i in range(n - 1):
        notify(db, Evento.AJUSTE_SEMAFORO_ROJO, [user], {"ajuste": f"A{i}", "corte": "C1"}, dedupe_key=f"t{i}")
    db.commit()


def test_notificaciones_contrato_y_filtros(client, db, world, auth):
    _crear_notifs(db, world.estudiante_user, 3)
    _crear_notifs(db, world.bienestar, 2)
    h = auth(world.estudiante_user)
    r = client.get(f"{API}/notificaciones", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert set(j) >= {"items", "total", "no_leidas"} and j["total"] == 3 and j["no_leidas"] == 3
    assert set(j["items"][0]) == {"id", "tipo", "titulo", "mensaje", "leida", "created_at", "enlace"}
    assert any(i["enlace"] == "/estudiante/plan" for i in j["items"])
    nid = j["items"][0]["id"]
    leer = client.post(f"{API}/notificaciones/{nid}/leer", headers=h)
    assert leer.status_code == 200 and leer.json()["no_leidas"] == 2
    assert client.get(f"{API}/notificaciones?solo_no_leidas=true", headers=h).json()["total"] == 2
    assert client.get(f"{API}/notificaciones?page=1&page_size=1", headers=h).json()["items"].__len__() == 1
    # ajena -> 404; propia de otro usuario no se filtra
    ajena = db.scalar(select(Notificacion.id).where(Notificacion.usuario_id == world.bienestar.id))
    assert client.post(f"{API}/notificaciones/{ajena}/leer", headers=h).status_code == 404
    todas = client.post(f"{API}/notificaciones/leer-todas", headers=h).json()
    assert todas["marcadas"] == 2 and todas["no_leidas"] == 0
    assert client.get(f"{API}/notificaciones", headers=h).json()["no_leidas"] == 0
    assert client.get(f"{API}/notificaciones", headers=auth(world.bienestar)).json()["no_leidas"] == 2  # las de otros intactas
    assert client.get(f"{API}/notificaciones").status_code == 401


def test_notificaciones_estudiante_sin_f0_puede_leer_las_suyas_y_outbox_solo_admin(client, db, world, auth):
    u, _ = make_estudiante(db, world.programa, consent=False)
    notify(db, Evento.CONSENTIMIENTO_PENDIENTE, [u])
    db.commit()
    r = client.get(f"{API}/notificaciones", headers=auth(u))
    assert r.status_code == 200 and r.json()["items"][0]["tipo"] == "CONSENTIMIENTO_PENDIENTE"
    assert client.get(f"{API}/notificaciones/outbox", headers=auth(u)).status_code == 403
    o = client.get(f"{API}/notificaciones/outbox", headers=auth(world.admin)).json()
    assert o["total"] >= 1 and "cuerpo_texto" not in o["items"][0]
