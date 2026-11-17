"""Motor DUA M3 (CBR + reglas), decisiones, privacidad del ai_gateway (RF-11/16, D4)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from sqlalchemy import select

import app.services.ai_gateway as ai_gateway
from app.models import LogAuditoria
from app.models.dua import CasoCbr, EstrategiaDuaCatalogo
from app.models.enums import Escenario, PrincipioDua, TipoBarrera
from app.services import cbr
from app.services import sugerencias as sug_svc
from app.services.ai_gateway import AIPrivacyError, AIPromptInput, generate_accessible_text
from scripts.seed import seed_reference
from tests.slice_b_helpers import fill_and_confirm_f1, h

API = "/api/v1"


def u(w):
    return f"{API}/estudiantes/{w.estudiante.id}"


@pytest.fixture()
def ready(client, db, world):
    seed_reference(db)
    db.commit()
    fill_and_confirm_f1(client, world.bienestar, world.estudiante.id)
    r = client.post(f"{u(world)}/barreras", headers=h(world.bienestar), json={
        "tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "descripcion_barrera": "Instrucciones solo orales.", "severidad": "SEVERA"})
    assert r.status_code == 201
    return world, r.json()["id"]


def _estrategia_comunicativa(db):
    for e in db.scalars(select(EstrategiaDuaCatalogo)):
        if "COMUNICATIVA" in e.tipos_barrera and "AULA" in e.escenarios:
            return e
    raise AssertionError("el catálogo semilla debe tener una estrategia COMUNICATIVA/AULA")


# ------------------------------------------------------------------ generación
def test_generar_por_reglas_con_justificacion_y_sin_duplicar(client, db, ready):
    w, bid = ready
    r = client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(w.bienestar))
    assert r.status_code == 201, r.text
    j = r.json()
    assert 1 <= len(j["creadas"]) <= 3 and j["barreras_sin_cobertura"] == []
    s0 = j["creadas"][0]
    assert s0["origen"] == "FILTRO_CATALOGO" and s0["estado"] == "PROPUESTA" and 0 < s0["puntaje"] <= 1
    assert s0["justificacion"].startswith("Esta estrategia es pertinente porque el estudiante tiene barrera de tipo COMUNICATIVA en el escenario AULA.")
    assert "severa" in s0["justificacion"] and "sugerencia" in s0["justificacion"].lower()
    assert all(c["tipo_barrera"] == "COMUNICATIVA" and "COMUNICATIVA" in c["estrategia"]["tipos_barrera"] for c in j["creadas"])
    # idempotente: no duplica
    j2 = client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(w.bienestar)).json()
    assert j2["creadas"] == [] and len(j2["actualizadas"]) == len(j["creadas"])
    # filtros
    todas = client.get(f"{u(w)}/sugerencias", headers=h(w.bienestar)).json()
    assert todas["total"] == len(j["creadas"])
    pr = s0["principio_dua"]
    f = client.get(f"{u(w)}/sugerencias?principio={pr}&escenario=AULA&tipo_barrera=COMUNICATIVA&pauta={s0['estrategia']['pauta']}", headers=h(w.bienestar)).json()
    assert f["total"] >= 1 and all(i["principio_dua"] == pr for i in f["items"])
    assert client.get(f"{u(w)}/sugerencias?tipo_barrera=SOCIAL", headers=h(w.bienestar)).json()["total"] == 0
    assert any(a.accion == "SUGERENCIAS_DUA_GENERADAS" for a in db.scalars(select(LogAuditoria)))


def test_sin_barreras_409(client, db, world):
    seed_reference(db)
    db.commit()
    r = client.post(f"{u(world)}/sugerencias/generar", json={}, headers=h(world.bienestar))
    assert r.status_code == 409 and r.json()["code"] == "SIN_BARRERAS"


def test_cbr_con_casos_suficientes_prioriza_la_estrategia_efectiva(client, db, ready):
    w, _ = ready
    objetivo = _estrategia_comunicativa(db)
    perfil = {"tipos_barrera": ["COMUNICATIVA"], "escenarios": ["AULA"], "principios": [str(objetivo.principio)], "severidad_max": "SEVERA", "rasgos": []}
    for _ in range(4):
        db.add(CasoCbr(estrategia_catalogo_id=objetivo.id, perfil=perfil, resultado_semaforo="VERDE", exitoso=True, origen="TEST"))
    db.commit()
    j = client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(w.bienestar)).json()
    primera = j["creadas"][0]
    assert primera["estrategia"]["id"] == objetivo.id and primera["origen"] == "CBR"
    assert "caso(s) anterior(es)" in primera["justificacion"] and "100%" in primera["justificacion"]


def test_casos_negativos_bajan_el_puntaje_en_modo_reglas(db, world):
    seed_reference(db)
    db.commit()
    objetivo = _estrategia_comunicativa(db)
    from datetime import date

    from app.models.mapa import BarreraIdentificada

    b = BarreraIdentificada(estudiante_id=world.estudiante.id, tipo_barrera="COMUNICATIVA", escenario="AULA",
                            descripcion_barrera="x", fecha_identificacion=date.today())
    db.add(b)
    db.flush()
    base = {r.estrategia.id: r.puntaje for r in cbr.recommend(db, world.estudiante.id, [b], max_por_barrera=10)[0]}
    perfil = {"tipos_barrera": ["COMUNICATIVA"], "escenarios": ["AULA"], "principios": [str(objetivo.principio)], "severidad_max": "MODERADA", "rasgos": []}
    db.add(CasoCbr(estrategia_catalogo_id=objetivo.id, perfil=perfil, exitoso=False, origen="RECHAZO_BIENESTAR", peso=0.5))
    db.flush()
    despues = {r.estrategia.id: r.puntaje for r in cbr.recommend(db, world.estudiante.id, [b], max_por_barrera=10)[0]}
    assert despues[objetivo.id] < base[objetivo.id]


def test_perfil_cbr_no_contiene_identidad(db, world):
    from datetime import date

    from app.models.caracterizacion import Caracterizacion, DatoSensorial

    car = Caracterizacion(estudiante_id=world.estudiante.id, fecha_caracterizacion=date.today(), profesional_responsable_id=world.bienestar.id)
    db.add(car)
    db.flush()
    db.add(DatoSensorial(caracterizacion_id=car.id, tipo_sensorial="AUDITIVA", hipersensibilidad=True, descripcion_experiencia="texto libre"))
    db.flush()
    rasgos = cbr.functional_traits(db, world.estudiante.id)
    assert rasgos == ["SENS_AUDITIVA"]  # solo etiquetas de enum, nunca texto libre ni ids


# ------------------------------------------------------------------ decisiones
def test_aceptar_modificar_rechazar_y_get_accepted(client, db, ready):
    w, _ = ready
    items = client.post(f"{u(w)}/sugerencias/generar", json={"max_por_barrera": 3}, headers=h(w.bienestar)).json()["creadas"]
    assert len(items) >= 3
    a, m, r_ = items[0], items[1], items[2]
    assert client.post(f"{API}/sugerencias/{a['id']}/aceptar", headers=h(w.bienestar)).json()["estado"] == "ACEPTADA"
    mod = client.post(f"{API}/sugerencias/{m['id']}/modificar", json={"texto_modificado": "Versión editada por Bienestar."}, headers=h(w.bienestar)).json()
    assert mod["estado"] == "MODIFICADA" and mod["texto_modificado"] == "Versión editada por Bienestar."
    # rechazo exige motivo
    bad = client.post(f"{API}/sugerencias/{r_['id']}/rechazar", json={"motivo": "no"}, headers=h(w.bienestar))
    assert bad.status_code == 422
    rej = client.post(f"{API}/sugerencias/{r_['id']}/rechazar", json={"motivo": "No es viable en este programa."}, headers=h(w.bienestar)).json()
    assert rej["estado"] == "RECHAZADA" and rej["motivo_decision"] == "No es viable en este programa."
    # retroalimenta el CBR: caso negativo anónimo
    caso = db.scalar(select(CasoCbr).where(CasoCbr.origen == "RECHAZO_BIENESTAR"))
    assert caso and caso.exitoso is False and caso.estrategia_catalogo_id == r_["estrategia"]["id"] and caso.plan_id is None
    assert set(caso.perfil) == {"tipos_barrera", "escenarios", "principios", "severidad_max", "rasgos"}
    # ya decidida
    assert client.post(f"{API}/sugerencias/{a['id']}/aceptar", headers=h(w.bienestar)).json()["code"] == "SUGERENCIA_YA_DECIDIDA"
    # lo rechazado no reaparece al regenerar
    again = client.post(f"{u(w)}/sugerencias/generar", json={"max_por_barrera": 3}, headers=h(w.bienestar)).json()
    assert r_["estrategia"]["id"] not in [c["estrategia"]["id"] for c in again["creadas"]]
    # get_accepted para el borrador F6 (slice C1)
    db.expire_all()
    acc = sug_svc.get_accepted(db, w.estudiante.id)
    assert {s.id for s in acc} == {a["id"], m["id"]}
    acciones = {x.accion for x in db.scalars(select(LogAuditoria))}
    assert {"SUGERENCIA_DUA_ACEPTADA", "SUGERENCIA_DUA_MODIFICADA", "SUGERENCIA_DUA_RECHAZADA"} <= acciones


def test_matriz_sugerencias(client, db, ready):
    w, _ = ready
    items = client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(w.bienestar)).json()["creadas"]
    sid = items[0]["id"]
    # solo Bienestar genera y decide
    for no in (w.coordinador, w.estudiante_user, w.docente, w.admin, w.familiar):
        assert client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(no)).status_code == 403, no.rol
        assert client.post(f"{API}/sugerencias/{sid}/aceptar", headers=h(no)).status_code == 403, no.rol
    # coordinador lee; docente no; estudiante solo ve lo acordado
    assert client.get(f"{u(w)}/sugerencias", headers=h(w.coordinador)).json()["total"] == len(items)
    assert client.get(f"{u(w)}/sugerencias", headers=h(w.docente)).status_code == 403
    assert client.get(f"{u(w)}/sugerencias", headers=h(w.estudiante_user)).json()["total"] == 0
    assert client.get(f"{API}/sugerencias/{sid}", headers=h(w.estudiante_user)).status_code == 403
    client.post(f"{API}/sugerencias/{sid}/aceptar", headers=h(w.bienestar))
    assert client.get(f"{u(w)}/sugerencias", headers=h(w.estudiante_user)).json()["total"] == 1
    assert client.get(f"{API}/sugerencias/{sid}", headers=h(w.estudiante_user)).status_code == 200
    assert client.get(f"{u(w)}/sugerencias", headers=h(w.otro_estudiante_user)).status_code == 403
    cat = client.get(f"{API}/sugerencias/catalogo?escenario=AULA&tipo_barrera=COMUNICATIVA", headers=h(w.docente)).json()
    assert cat["total"] >= 1


def test_texto_accesible_endpoint_usa_plantilla_sin_clave(client, ready, monkeypatch):
    w, _ = ready
    monkeypatch.setattr(ai_gateway, "_get_client", lambda: None)
    sid = client.post(f"{u(w)}/sugerencias/generar", json={}, headers=h(w.bienestar)).json()["creadas"][0]["id"]
    r = client.post(f"{API}/sugerencias/{sid}/texto-accesible", headers=h(w.bienestar))
    assert r.status_code == 200 and r.json()["origen"] == "PLANTILLA"
    assert "aula" in r.json()["texto_accesible"].lower()
    assert client.get(f"{API}/sugerencias/{sid}", headers=h(w.bienestar)).json()["texto_accesible"] == r.json()["texto_accesible"]


# ------------------------------------------------------------------ privacidad IA (RF-11 / RF-16 / D4)
class _SpyClient:
    def __init__(self):
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = "Texto generado por el modelo."

        return R()


def _prompt():
    return AIPromptInput(TipoBarrera.COMUNICATIVA, Escenario.AULA, PrincipioDua.REPRESENTACION)


def test_a_el_payload_enviado_contiene_unicamente_los_tres_campos(monkeypatch):
    spy = _SpyClient()
    monkeypatch.setattr(ai_gateway, "_get_client", lambda: spy)
    res = generate_accessible_text(_prompt())
    assert res.origen == "OPENAI" and len(spy.calls) == 1
    (rol_s, sistema), (rol_h, humano) = spy.calls[0]
    assert (rol_s, rol_h) == ("system", "human")
    payload = json.loads(humano)
    assert set(payload) == {"tipo_barrera", "escenario", "principio_dua"}
    assert payload == {"tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "principio_dua": "REPRESENTACION"}
    for prohibido in ("nombre", "puntaje", "aq10", "diagnostico", "estudiante_id", "email"):
        assert prohibido not in humano.lower()


def test_b_cualquier_otro_dato_falla(monkeypatch):
    spy = _SpyClient()
    monkeypatch.setattr(ai_gateway, "_get_client", lambda: spy)
    for extra in ("nombre", "puntaje_aq10", "diagnostico", "estudiante_id"):
        with pytest.raises((TypeError, AIPrivacyError)):
            AIPromptInput(TipoBarrera.COMUNICATIVA, Escenario.AULA, PrincipioDua.REPRESENTACION, **{extra: "x"})
        with pytest.raises(AIPrivacyError):
            AIPromptInput.from_mapping({"tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "principio_dua": "REPRESENTACION", extra: "x"})
    with pytest.raises(AIPrivacyError):
        AIPromptInput("Juan Pérez", Escenario.AULA, PrincipioDua.REPRESENTACION)  # valores fuera de los enums
    with pytest.raises(AIPrivacyError):
        generate_accessible_text({"tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "principio_dua": "REPRESENTACION"})  # type: ignore[arg-type]
    with pytest.raises(AIPrivacyError):
        generate_accessible_text("Juan Pérez tiene AQ-10 de 8")  # type: ignore[arg-type]
    with pytest.raises(AttributeError):  # inmutable: no se puede añadir un campo después
        _prompt().nombre = "x"  # type: ignore[attr-defined]
    assert spy.calls == []  # nada llegó al cliente


def test_c_sin_clave_devuelve_plantilla(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    from app.core import config

    config.reset_settings_cache()
    res = generate_accessible_text(_prompt())
    assert res.origen == "PLANTILLA" and "aula" in res.texto.lower() and res.modelo is None
    # con clave pero cliente que falla: también degrada a plantilla
    class Boom:
        def invoke(self, _m):
            raise RuntimeError("sin red")

    monkeypatch.setattr(ai_gateway, "_get_client", lambda: Boom())
    assert generate_accessible_text(_prompt()).origen == "PLANTILLA"


def test_d_ai_gateway_no_importa_aq10_ni_modelos_de_usuario():
    src = Path(ai_gateway.__file__).read_text(encoding="utf-8")
    importados = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            importados |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            importados.add(node.module or "")
            importados |= {f"{node.module}.{a.name}" for a in node.names}
    prohibidos = ("app.data.aq10", "app.services.aq10", "app.models.usuarios", "app.models.consentimiento",
                  "app.models.caracterizacion", "app.services.aq10_config")
    malos = [i for i in importados if any(i == p or i.startswith(p + ".") for p in prohibidos)]
    assert malos == []
    assert {i for i in importados if i.startswith("app.")} <= {"app.core.config", "app.models.enums", "app.models.enums.Escenario",
                                                              "app.models.enums.PrincipioDua", "app.models.enums.TipoBarrera",
                                                              "app.core.config.get_settings"}
    nombres = {n for n in vars(ai_gateway) if n in ("Usuario", "Estudiante", "RespuestaAQ10", "aq10")}
    assert nombres == set()


def test_seed_extra_b_idempotente_y_motor_en_modo_cbr(db, world):
    from scripts.seed_extra_b import seed

    seed_reference(db)
    db.commit()
    r1 = seed(db)
    db.commit()
    assert r1["casos_cbr"] > 20
    assert seed(db)["casos_cbr"] == 0
    assert all(c.origen == "SEED_DEMO" and "estudiante" not in str(c.perfil).lower() for c in db.scalars(select(CasoCbr)))
