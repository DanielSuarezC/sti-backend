"""Slice C2: tablero de estudiantes, «Mi ruta» (12 pasos), pendientes, asignacion de Bienestar e inasistencia (RF-31)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import CuestionarioAQ10, EmailOutbox, LogAuditoria, RegistroInasistencia, RespuestaAQ10
from app.models.base import utcnow
from app.models.enums import ModalidadAQ10, Semaforo
from app.services.params import set_param
from tests.factories import make_estudiante, make_user
from tests.test_slice_c2_common import Api, make_calendario, make_plan_impl


@pytest.fixture()
def api(client):
    return Api(client)


def _aq10(db, est, bienestar, puntaje=8):
    c = CuestionarioAQ10(nombre="AQ-10", version="t", items=[], opciones=[], punto_corte=6, activo=True)
    db.add(c)
    db.flush()
    db.add(RespuestaAQ10(estudiante_id=est.id, cuestionario_id=c.id, aplicado_por_id=bienestar.id, modalidad=ModalidadAQ10.ASISTIDA,
                         aplicado_at=utcnow(), respuestas={"1": 1}, puntaje=puntaje, punto_corte_aplicado=6,
                         supera_umbral=True, flujo_activado=True))
    db.commit()


# ----------------------------------------------------------------------------- listado
def test_listado_por_rol_y_sin_datos_clinicos(api, db, world):
    w = world
    _aq10(db, w.estudiante, w.bienestar)
    _, ajeno = make_estudiante(db, w.otro_programa)
    ids = lambda r: {x["id"] for x in r.json()["items"]}  # noqa: E731
    r = api.get(w.bienestar, "/estudiantes")
    assert r.status_code == 200 and ids(r) == {w.estudiante.id, w.otro_estudiante.id, ajeno.id}
    assert ids(api.get(w.coordinador, "/estudiantes")) == {w.estudiante.id, w.otro_estudiante.id}  # solo su programa
    assert ids(api.get(w.coordinador_otro, "/estudiantes")) == {ajeno.id}
    assert ids(api.get(w.admin, "/estudiantes")) == {w.estudiante.id, w.otro_estudiante.id, ajeno.id}
    for u in (w.docente, w.estudiante_user, w.familiar):
        assert api.get(u, "/estudiantes").status_code == 403
    assert api.get(w.bienestar, "/estudiantes").status_code == 200
    assert api.c.get("/api/v1/estudiantes").status_code == 401
    # NUNCA AQ-10 ni datos clinicos en el listado
    for u in (w.bienestar, w.coordinador, w.admin):
        texto = json.dumps(api.get(u, "/estudiantes").json()).lower()
        for prohibido in ("aq10", "aq-10", "puntaje", "diagnostico", "caracterizacion", "tipo_tea", "contacto_emergencia"):
            assert prohibido not in texto, (u.rol, prohibido)


def test_listado_filtros_y_paginacion(api, db, world):
    w = world
    plan, _ = make_plan_impl(db, w)
    plan.semaforo_actual = Semaforo.ROJO
    db.commit()
    r = api.get(w.bienestar, "/estudiantes?semaforo=ROJO").json()
    assert [x["id"] for x in r["items"]] == [w.estudiante.id] and r["items"][0]["semaforo_agregado"] == "ROJO"
    assert r["items"][0]["plan"]["estado"] == "IMPLEMENTACION"
    assert [x["id"] for x in api.get(w.bienestar, "/estudiantes?semaforo=SIN_SEMAFORO").json()["items"]] == [w.otro_estudiante.id]
    assert api.get(w.bienestar, "/estudiantes?estado_plan=IMPLEMENTACION").json()["total"] == 1
    assert api.get(w.bienestar, "/estudiantes?estado=ACTIVO").json()["total"] == 2
    assert api.get(w.bienestar, "/estudiantes?estado=SUSPENDIDO").json()["total"] == 0
    assert api.get(w.bienestar, f"/estudiantes?q={w.estudiante.codigo_estudiante[:4].lower()}").json()["total"] == 2
    assert api.get(w.bienestar, f"/estudiantes?q={w.estudiante.codigo_estudiante.lower()}").json()["total"] == 1
    assert api.get(w.bienestar, "/estudiantes?con_pendientes=true").json()["total"] == 2
    assert api.get(w.bienestar, "/estudiantes?con_pendientes=false").json()["total"] == 0
    p = api.get(w.bienestar, "/estudiantes?page=2&page_size=1").json()
    assert p["page"] == 2 and p["page_size"] == 1 and p["total"] == 2 and len(p["items"]) == 1
    assert api.get(w.bienestar, "/estudiantes?page_size=1000").status_code == 422


def test_resumen_segun_rol(api, db, world):
    w = world
    _aq10(db, w.estudiante, w.bienestar)
    j = api.get(w.bienestar, f"/estudiantes/{w.estudiante.id}").json()
    assert j["aq10"] == {"aplicado": True, "ruta_activada": True} and "puntaje" not in json.dumps(j).lower()
    assert "aq10" not in api.get(w.coordinador, f"/estudiantes/{w.estudiante.id}").json()
    assert "ruta" not in api.get(w.admin, f"/estudiantes/{w.estudiante.id}").json()
    assert api.get(w.estudiante_user, f"/estudiantes/{w.estudiante.id}").status_code == 200
    for u in (w.coordinador_otro, w.otro_estudiante_user, w.docente, w.familiar):
        assert api.get(u, f"/estudiantes/{w.estudiante.id}").status_code == 403
    assert api.get(w.bienestar, "/estudiantes/99999").status_code == 404


# ----------------------------------------------------------------------------- mi ruta
def test_mi_ruta_sin_f0_lleva_a_firmar(api, db, world):
    u, est = make_estudiante(db, world.programa, consent=False)
    r = api.get(u, "/estudiantes/mi-ruta")
    assert r.status_code == 200
    j = r.json()
    assert len(j["pasos"]) == 12 and all(p["estado"] == "pendiente" for p in j["pasos"])
    assert j["previos"][0] == {"codigo": "F0", "nombre": "Consentimiento informado", "estado": "actual",
                               "ruta_frontend": "/estudiante/consentimiento"}
    assert j["siguiente"]["ruta_frontend"] == "/estudiante/consentimiento" and j["paso_actual"] is None
    assert api.get(u, f"/estudiantes/{est.id}/pendientes").json()["items"][0]["codigo"] == "F0"


def test_mi_ruta_calcula_los_12_pasos_desde_los_datos(api, db, world):
    w = world
    make_calendario(db)
    plan, aj = make_plan_impl(db, w)
    r = api.get(w.estudiante_user, "/estudiantes/mi-ruta")
    j = r.json()
    assert [p["numero"] for p in j["pasos"]] == list(range(1, 13))
    estado = {p["numero"]: p["estado"] for p in j["pasos"]}
    assert estado[1] == "actual" and estado[8] == "hecho" and estado[9] == "hecho" and estado[11] == "pendiente"
    assert estado[10] == "pendiente" or estado[10] == "actual"
    assert j["pasos"][0]["modulo"] == "M2" and j["pasos"][0]["formato"] == "F1" and j["pasos"][9]["formato"] == "F8"
    assert j["plan"]["estado"] == "IMPLEMENTACION" and j["progreso"] == {"hechos": 3, "total": 12} and estado[4] == "hecho"
    # seguimiento abierto sin percepcion -> pendiente del estudiante con ruta del estudiante
    api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1")
    j = api.get(w.estudiante_user, "/estudiantes/mi-ruta").json()
    assert {p["codigo"] for p in api.get(w.estudiante_user, f"/estudiantes/{w.estudiante.id}/pendientes").json()["items"]} >= {"PERCEPCION_PENDIENTE"}
    assert j["siguiente"]["ruta_frontend"].startswith("/estudiante/")
    assert next(p for p in j["pasos"] if p["numero"] == 10)["detalle"] == "C1 abierto"
    # Bienestar ve sus propios pendientes (incluye abrir/completar F8) con rutas de Bienestar
    pend = api.get(w.bienestar, f"/estudiantes/{w.estudiante.id}/pendientes").json()["items"]
    assert any(p["codigo"] == "F8_ABIERTO" and p["ruta_frontend"] == f"/bienestar/estudiantes/{w.estudiante.id}/seguimiento" for p in pend)


def test_ruta_y_pendientes_alcance_y_privacidad(api, db, world):
    w = world
    _aq10(db, w.estudiante, w.bienestar)
    rb = api.get(w.bienestar, f"/estudiantes/{w.estudiante.id}/ruta").json()
    rc = api.get(w.coordinador, f"/estudiantes/{w.estudiante.id}/ruta").json()
    assert [p["codigo"] for p in rb["previos"]] == ["F0", "AQ10"] and rb["ruta_activada"] is True
    assert [p["codigo"] for p in rc["previos"]] == ["F0"] and "ruta_activada" not in rc
    for u in (w.docente, w.familiar, w.admin, w.coordinador_otro, w.otro_estudiante_user):
        assert api.get(u, f"/estudiantes/{w.estudiante.id}/ruta").status_code == 403
        assert api.get(u, f"/estudiantes/{w.estudiante.id}/pendientes").status_code == 403
    assert api.get(w.bienestar, "/estudiantes/mi-ruta").status_code == 403  # solo estudiantes


# ----------------------------------------------------------------------------- asignacion
def test_asignar_bienestar(api, db, world):
    w = world
    otro_b = make_user(db, "BIENESTAR")
    url = f"/estudiantes/{w.estudiante.id}/bienestar"
    r = api.put(w.bienestar, url, {"bienestar_usuario_id": otro_b.id})
    assert r.status_code == 200 and r.json()["bienestar_asignado"]["id"] == otro_b.id
    db.refresh(w.estudiante)
    assert w.estudiante.bienestar_asignado_id == otro_b.id
    assert api.put(w.admin, url, {"bienestar_usuario_id": None}).json()["bienestar_asignado"] is None
    assert api.put(w.bienestar, url, {"bienestar_usuario_id": w.docente.id}).status_code == 422  # no es Bienestar
    for u in (w.coordinador, w.docente, w.estudiante_user):
        assert api.put(u, url, {"bienestar_usuario_id": otro_b.id}).status_code == 403
    assert db.query(LogAuditoria).filter_by(accion="ASIGNACION_BIENESTAR").count() == 2


# ----------------------------------------------------------------------------- inasistencia
def _correos(db):
    return {e.usuario_id for e in db.scalars(select(EmailOutbox).where(EmailOutbox.evento == "INASISTENCIA_UMBRAL"))}


def test_inasistencia_bajo_umbral_no_alerta(api, db, world):
    w = world
    make_calendario(db)
    r = api.post(w.bienestar, f"/estudiantes/{w.estudiante.id}/inasistencia", {"porcentaje_inasistencia": 12.5})
    assert r.status_code == 201
    j = r.json()
    assert j["umbral"] == 20.0 and j["supera_umbral"] is False and j["alerta_enviada"] is False
    assert j["registro"]["semestre_academico"] == "2026-II" and j["registro"]["fuente"] == "MANUAL"
    assert _correos(db) == set()


def test_inasistencia_sobre_umbral_alerta_a_bienestar_y_coordinador_una_vez_por_periodo(api, db, world):
    w = world
    make_calendario(db)
    url = f"/estudiantes/{w.estudiante.id}/inasistencia"
    r = api.post(w.bienestar, url, {"porcentaje_inasistencia": 20})  # igual al umbral = alerta (>=)
    assert r.json()["alerta_enviada"] is True and r.json()["registro"]["alerta_generada"] is True
    assert _correos(db) == {w.bienestar.id, w.coordinador.id}  # nadie mas (ni coordinador de otro programa)
    r = api.post(w.bienestar, url, {"porcentaje_inasistencia": 35})  # mismo periodo: sin segunda alerta
    assert r.json()["alerta_enviada"] is False and r.json()["alerta_ya_enviada_en_el_periodo"] is True
    assert db.query(EmailOutbox).filter_by(evento="INASISTENCIA_UMBRAL").count() == 2
    # otro periodo: nueva alerta
    r = api.post(w.bienestar, url, {"porcentaje_inasistencia": 40, "semestre_academico": "2027-I"})
    assert r.json()["alerta_enviada"] is True
    assert db.query(EmailOutbox).filter_by(evento="INASISTENCIA_UMBRAL").count() == 4
    assert db.query(RegistroInasistencia).count() == 3


def test_inasistencia_respeta_el_parametro_umbral(api, db, world):
    w = world
    make_calendario(db)
    set_param(db, "umbral_inasistencia", 10)
    db.commit()
    r = api.post(w.bienestar, f"/estudiantes/{w.estudiante.id}/inasistencia", {"porcentaje_inasistencia": 12})
    assert r.json()["umbral"] == 10.0 and r.json()["alerta_enviada"] is True


def test_inasistencia_validacion_rbac_y_sigaa_apagado(api, db, world, monkeypatch):
    w = world
    make_calendario(db)
    url = f"/estudiantes/{w.estudiante.id}/inasistencia"
    assert api.post(w.bienestar, url, {"porcentaje_inasistencia": 120}).status_code == 422
    assert api.post(w.bienestar, url, {"porcentaje_inasistencia": -1}).status_code == 422
    for u in (w.coordinador, w.docente, w.estudiante_user, w.familiar, w.admin):
        assert api.post(u, url, {"porcentaje_inasistencia": 30}).status_code == 403
    # lectura: Bienestar, Coordinador y el propio estudiante
    api.post(w.bienestar, url, {"porcentaje_inasistencia": 5})
    for u in (w.bienestar, w.coordinador, w.estudiante_user):
        assert api.get(u, url).json()["items"][0]["porcentaje_inasistencia"] == 5.0
    assert api.get(w.otro_estudiante_user, url).status_code == 403
    # SIGAA desactivado por defecto
    monkeypatch.delenv("SIGAA_API_URL", raising=False)
    r = api.post(w.bienestar, url + "/sigaa")
    assert r.status_code == 501 and r.json()["code"] == "SIGAA_NO_CONFIGURADO"
    # SIGAA configurado pero caido -> 502 y registrar manualmente (R6)
    monkeypatch.setenv("SIGAA_API_URL", "http://127.0.0.1:9")
    r = api.post(w.bienestar, url + "/sigaa")
    assert r.status_code == 502 and r.json()["code"] == "SIGAA_NO_DISPONIBLE"
