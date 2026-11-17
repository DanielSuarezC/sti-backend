"""AQ-10: puntuación en backend, umbral, flujo MAAR-TEA, cifrado, matriz de acceso y auditoría."""

from __future__ import annotations

from sqlalchemy import select, text

from app.models import LogAuditoria
from app.models.caracterizacion import Caracterizacion
from app.models.consentimiento import RespuestaAQ10
from app.models.sistema import EmailOutbox, Notificacion
from app.services import params
from tests.factories import authorize_familiar
from tests.slice_b_helpers import aq10_answers, h

API = "/api/v1"


def _post(client, user, est_id, puntaje):
    return client.post(f"{API}/estudiantes/{est_id}/aq10", json={"respuestas": aq10_answers(puntaje)}, headers=h(user))


def test_formulario_items_opciones_protocolo(client, world):
    r = client.get(f"{API}/aq10/formulario", headers=h(world.estudiante_user))
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) == 10 and [o["valor"] for o in j["opciones"]] == [1, 2, 3, 4]
    assert "puntua_si" not in str(j["items"])  # la lógica de puntuación no sale al cliente
    assert j["protocolo_bienvenida"]["pasos"] and "tamizaje" in j["mensaje_tamizaje"].lower()
    for u in (world.docente, world.coordinador, world.familiar, world.admin):
        assert client.get(f"{API}/aq10/formulario", headers=h(u)).status_code == 403


def test_asistida_puntaje_6_activa_flujo_notifica_y_cifra(client, db, world):
    w = world
    r = _post(client, w.bienestar, w.estudiante.id, 6)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["puntaje"] == 6 and j["supera_umbral"] is True and j["modalidad"] == "ASISTIDA"
    assert j["ruta_maar_tea_activada"] and j["f1_pendiente_creada"]
    assert "diagn" in j["mensaje"].lower()
    db.expire_all()
    f1 = db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == w.estudiante.id))
    assert f1 is not None and str(f1.estado) == "INCOMPLETA"
    assert db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "AQ10_POSITIVO", EmailOutbox.usuario_id == w.bienestar.id))
    assert db.scalar(select(Notificacion).where(Notificacion.tipo == "AQ10_POSITIVO", Notificacion.usuario_id == w.bienestar.id))
    # el cuerpo del aviso no contiene el puntaje
    mail = db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "AQ10_POSITIVO"))
    assert "6/10" not in mail.cuerpo_texto
    # respuestas y puntaje cifrados en reposo
    raw = db.execute(text("SELECT respuestas, puntaje FROM respuesta_aq10")).one()
    assert raw[0].startswith("v1:") and raw[1].startswith("v1:")
    row = db.scalar(select(RespuestaAQ10))
    assert row.puntaje == 6 and row.flujo_activado and row.punto_corte_aplicado == 6
    # no quedó el puntaje en la auditoría
    for log in db.scalars(select(LogAuditoria).where(LogAuditoria.accion.in_(["APLICACION_AQ10", "AQ10_FLUJO_ACTIVADO"]))):
        assert "puntaje" not in str(log.detalle) or "***" in str(log.detalle)


def test_puntaje_5_archiva_y_devuelve_recursos(client, db, world):
    r = _post(client, world.bienestar, world.estudiante.id, 5)
    j = r.json()
    assert j["puntaje"] == 5 and j["supera_umbral"] is False and j["ruta_maar_tea_activada"] is False
    assert j["recursos_bienestar"] and "volver a solicitarlo" in j["mensaje"]
    assert db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == world.estudiante.id)) is None


def test_corte_configurable_por_parametro(client, db, world):
    params.set_param(db, "aq10_punto_corte", 4)
    db.commit()
    j = _post(client, world.bienestar, world.estudiante.id, 5).json()
    assert j["supera_umbral"] is True and j["punto_corte_aplicado"] == 4


def test_autoaplicacion_y_reaplicacion(client, world):
    w = world
    r = _post(client, w.estudiante_user, w.estudiante.id, 7)
    assert r.status_code == 201 and r.json()["modalidad"] == "AUTOAPLICADA"
    r = _post(client, w.estudiante_user, w.estudiante.id, 2)
    assert r.status_code == 409 and r.json()["code"] == "AQ10_YA_APLICADO"
    assert _post(client, w.bienestar, w.estudiante.id, 2).status_code == 201  # Bienestar puede repetir
    # un estudiante no aplica a otro
    assert _post(client, w.estudiante_user, w.otro_estudiante.id, 7).status_code == 403


def test_validaciones_de_respuestas(client, world):
    w = world
    r = client.post(f"{API}/estudiantes/{w.estudiante.id}/aq10", json={"respuestas": {"1": 1}}, headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "AQ10_INCOMPLETO"
    bad = aq10_answers(3)
    bad["2"] = 9
    r = client.post(f"{API}/estudiantes/{w.estudiante.id}/aq10", json={"respuestas": bad}, headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "AQ10_RESPUESTAS_INVALIDAS"


def test_matriz_lectura_solo_bienestar_y_propio_con_auditoria(client, db, world):
    w = world
    _post(client, w.bienestar, w.estudiante.id, 8)
    authorize_familiar(db, w.estudiante, w.familiar, ["CARACTERIZACION", "PLAN", "SEGUIMIENTO"])
    url = f"{API}/estudiantes/{w.estudiante.id}/aq10"
    assert client.get(url, headers=h(w.bienestar)).json()["items"][0]["puntaje"] == 8
    assert client.get(url, headers=h(w.estudiante_user)).json()["items"][0]["puntaje"] == 8
    for u in (w.docente, w.coordinador, w.familiar, w.admin, w.otro_estudiante_user, w.docente_otro):
        r = client.get(url, headers=h(u))
        assert r.status_code == 403, (u.rol, r.status_code)
    db.expire_all()
    accesos = db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "ACCESO_AQ10", LogAuditoria.estudiante_id == w.estudiante.id)).all()
    assert len(accesos) == 2 and {a.actor_rol for a in accesos} == {"BIENESTAR", "ESTUDIANTE"}
    # nadie más puede aplicar
    for u in (w.docente, w.coordinador, w.familiar, w.admin):
        assert _post(client, u, w.estudiante.id, 8).status_code == 403


def test_estudiante_sin_f0_no_accede(client, db, world):
    from tests.factories import make_estudiante

    u, est = make_estudiante(db, world.programa, consent=False)
    r = client.get(f"{API}/aq10/formulario", headers=h(u))
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
    assert _post(client, world.bienestar, est.id, 8).json()["code"] == "ESTUDIANTE_SIN_CONSENTIMIENTO"
