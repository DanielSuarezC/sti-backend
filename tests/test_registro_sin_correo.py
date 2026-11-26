"""Registro autónomo y recuperación SIN correo electrónico (prototipo en producción)."""

from __future__ import annotations

import pytest

from app.core.config import reset_settings_cache
from tests.factories import auth_headers

API = "/api/v1"
CLAVE = "ClaveSegura2026"


def _registro(client, **kw):
    body = {"rol": "ESTUDIANTE", "nombre_completo": "Ana María Pérez", "email": "ana@example.com", "password": CLAVE,
            "codigo_estudiante": "20261234", "acepta_aviso_privacidad": True, **kw}
    return client.post(f"{API}/auth/register", json=body)


def _login(client, email, password):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


@pytest.fixture()
def con_codigo_personal(monkeypatch):
    monkeypatch.setenv("STAFF_ACCESS_CODE", "codigo-del-personal-123")
    reset_settings_cache()
    yield
    monkeypatch.delenv("STAFF_ACCESS_CODE", raising=False)
    reset_settings_cache()


@pytest.fixture()
def registro_cerrado(monkeypatch):
    monkeypatch.setenv("REGISTRO_ABIERTO", "false")
    reset_settings_cache()
    yield
    monkeypatch.delenv("REGISTRO_ABIERTO", raising=False)
    reset_settings_cache()


# ----------------------------------------------------------------------------- registro
def test_estudiante_se_registra_y_entra_sin_correo(client, world):
    r = _registro(client, programa_id=world.programa.id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["rol"] == "ESTUDIANTE" and body["user"]["estado"] == "PENDIENTE_CONSENTIMIENTO"
    assert body["user"]["consentimiento_firmado"] is False
    assert len(body["codigo_recuperacion"].replace("-", "")) == 16
    # la sesión abierta funciona y el login posterior también
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "ana@example.com"
    assert _login(client, "ANA@example.com", CLAVE).status_code == 200


def test_registro_valida_datos(client, world):
    assert _registro(client, programa_id=world.programa.id).status_code == 201
    dup = _registro(client, programa_id=world.programa.id, codigo_estudiante="999")
    assert dup.status_code == 409 and dup.json()["code"] == "EMAIL_DUPLICADO"
    dup_cod = _registro(client, email="otra@example.com", programa_id=world.programa.id)
    assert dup_cod.status_code == 409 and dup_cod.json()["code"] == "CEDULA_DUPLICADA"
    debil = _registro(client, email="debil@example.com", codigo_estudiante="1", password="corta",
                      programa_id=world.programa.id)
    assert debil.status_code == 422 and debil.json()["code"] == "CONTRASENA_DEBIL"
    sin_aviso = _registro(client, email="sa@example.com", codigo_estudiante="2", acepta_aviso_privacidad=False,
                          programa_id=world.programa.id)
    assert sin_aviso.status_code == 422 and sin_aviso.json()["code"] == "AVISO_PRIVACIDAD_REQUERIDO"
    sin_prog = _registro(client, email="sp@example.com", codigo_estudiante="3")
    assert sin_prog.status_code == 422 and sin_prog.json()["code"] == "PROGRAMA_INVALIDO"
    sin_cod = _registro(client, email="sc@example.com", codigo_estudiante=None, programa_id=world.programa.id)
    assert sin_cod.status_code == 422 and sin_cod.json()["code"] == "CODIGO_ESTUDIANTE_REQUERIDO"


def test_docente_se_registra(client, world):
    r = _registro(client, rol="DOCENTE", email="doc@example.com", codigo_estudiante=None, programa_id=world.programa.id)
    assert r.status_code == 201, r.text
    assert r.json()["user"]["rol"] == "DOCENTE" and r.json()["user"]["estado"] == "ACTIVO"
    assert r.json()["user"]["programa_id"] == world.programa.id


def test_personal_exige_codigo_de_acceso(client, world):
    # sin STAFF_ACCESS_CODE configurado no hay registro libre de personal
    r = _registro(client, rol="BIENESTAR", email="b@example.com", codigo_estudiante=None)
    assert r.status_code == 403 and r.json()["code"] == "ROL_NO_DISPONIBLE_REGISTRO"
    opciones = client.get(f"{API}/auth/registro/opciones").json()
    assert "BIENESTAR" not in opciones["roles"] and "ESTUDIANTE" in opciones["roles"]
    # el administrador nunca se crea por registro libre
    assert client.post(f"{API}/auth/register", json={
        "rol": "ADMIN", "nombre_completo": "Intruso Admin", "email": "x@example.com", "password": CLAVE,
        "acepta_aviso_privacidad": True}).status_code == 422


def test_personal_con_codigo(client, world, con_codigo_personal):
    mal = _registro(client, rol="BIENESTAR", email="b@example.com", codigo_estudiante=None, codigo_acceso="no-es")
    assert mal.status_code == 403 and mal.json()["code"] == "CODIGO_PERSONAL_INCORRECTO"
    ok = _registro(client, rol="BIENESTAR", email="b@example.com", codigo_estudiante=None,
                   codigo_acceso="codigo-del-personal-123")
    assert ok.status_code == 201 and ok.json()["user"]["rol"] == "BIENESTAR"
    assert "BIENESTAR" in client.get(f"{API}/auth/registro/opciones").json()["roles"]


def test_registro_cerrado(client, world, registro_cerrado):
    r = _registro(client, programa_id=world.programa.id)
    assert r.status_code == 403 and r.json()["code"] == "REGISTRO_CERRADO"


# ----------------------------------------------------------------------------- recuperación con código
def test_recuperar_clave_con_codigo(client, world):
    codigo = _registro(client, programa_id=world.programa.id).json()["codigo_recuperacion"]
    malo = client.post(f"{API}/auth/recover", json={"email": "ana@example.com", "codigo_recuperacion": "AAAA-AAAA-AAAA-AAAA",
                                                    "password": "NuevaClave2026"})
    assert malo.status_code == 400 and malo.json()["code"] == "CODIGO_RECUPERACION_INVALIDO"
    ok = client.post(f"{API}/auth/recover", json={"email": "ana@example.com", "codigo_recuperacion": codigo.lower(),
                                                  "password": "NuevaClave2026"})
    assert ok.status_code == 200, ok.text
    nuevo = ok.json()["codigo_recuperacion"]
    assert nuevo != codigo
    assert _login(client, "ana@example.com", CLAVE).status_code == 401
    assert _login(client, "ana@example.com", "NuevaClave2026").status_code == 200
    # el código usado ya no sirve; el nuevo sí
    reuso = client.post(f"{API}/auth/recover", json={"email": "ana@example.com", "codigo_recuperacion": codigo,
                                                     "password": "OtraClave2026"})
    assert reuso.status_code == 400
    assert client.post(f"{API}/auth/recover", json={"email": "ana@example.com", "codigo_recuperacion": nuevo,
                                                    "password": "OtraClave2026"}).status_code == 200


def test_recuperar_no_revela_si_el_correo_existe(client, world):
    r = client.post(f"{API}/auth/recover", json={"email": "nadie@example.com", "codigo_recuperacion": "AAAA-AAAA-AAAA-AAAA",
                                                 "password": "NuevaClave2026"})
    assert r.status_code == 400 and r.json()["code"] == "CODIGO_RECUPERACION_INVALIDO"


def test_regenerar_codigo_pide_contrasena(client, world):
    reg = _registro(client, programa_id=world.programa.id).json()
    h = {"Authorization": f"Bearer {reg['access_token']}"}
    assert client.post(f"{API}/auth/recovery-code/regenerate", headers=h, json={"password": "incorrecta1"}).status_code == 400
    r = client.post(f"{API}/auth/recovery-code/regenerate", headers=h, json={"password": CLAVE})
    assert r.status_code == 200 and r.json()["codigo_recuperacion"] != reg["codigo_recuperacion"]
    viejo = client.post(f"{API}/auth/recover", json={"email": "ana@example.com", "codigo_recuperacion": reg["codigo_recuperacion"],
                                                     "password": "NuevaClave2026"})
    assert viejo.status_code == 400


# ----------------------------------------------------------------------------- cuentas creadas por el personal
def test_admin_crea_docente_con_clave_provisional(client, world, auth):
    r = client.post(f"{API}/usuarios", headers=auth(world.admin), json={
        "email": "nuevo.docente@example.com", "nombre_completo": "Nuevo Docente", "rol": "DOCENTE",
        "programa_id": world.programa.id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "ACTIVO" and body["acceso"]["modo"] == "DIRECTO"
    assert _login(client, "nuevo.docente@example.com", body["acceso"]["password_temporal"]).status_code == 200


def test_bienestar_crea_estudiante_via1_listo_para_entrar(client, world, auth):
    r = client.post(f"{API}/usuarios/estudiantes", headers=auth(world.bienestar), json={
        "nombre_completo": "Luis Gómez Ruiz", "email": "luis@example.com", "codigo_estudiante": "555",
        "programa_id": world.programa.id, "es_correo_personal": True})
    assert r.status_code == 201, r.text
    acceso = r.json()["acceso"]
    login = _login(client, "luis@example.com", acceso["password_temporal"])
    assert login.status_code == 200 and login.json()["user"]["estado"] == "PENDIENTE_CONSENTIMIENTO"


def test_restablecer_clave_por_el_personal(client, world, auth):
    est = world.estudiante_user
    r = client.post(f"{API}/usuarios/{est.id}/restablecer-clave", headers=auth(world.bienestar))
    assert r.status_code == 200, r.text
    assert _login(client, est.email, r.json()["acceso"]["password_temporal"]).status_code == 200
    # un docente no puede restablecer claves
    assert client.post(f"{API}/usuarios/{est.id}/restablecer-clave", headers=auth(world.docente)).status_code == 403
    # Bienestar no toca cuentas de otro personal
    assert client.post(f"{API}/usuarios/{world.admin.id}/restablecer-clave", headers=auth(world.bienestar)).status_code == 403


# ----------------------------------------------------------------------------- familiar con código de vinculación
def test_familiar_se_vincula_con_codigo(client, world):
    otorgar = client.post(f"{API}/estudiantes/mi/familiares", headers=auth_headers(world.estudiante_user), json={
        "nombre": "Marta Pérez", "email": "marta@example.com", "parentesco": "Madre", "alcance": {"plan": True}})
    assert otorgar.status_code == 201, otorgar.text
    aut = otorgar.json()
    assert aut["estado"] == "PENDIENTE" and len(aut["codigo_vinculacion"]) == 8
    body = {"rol": "FAMILIAR", "nombre_completo": "Marta Pérez", "email": "marta@example.com", "password": CLAVE,
            "acepta_aviso_privacidad": True}
    sin = client.post(f"{API}/auth/register", json=body)
    assert sin.status_code == 422 and sin.json()["code"] == "CODIGO_VINCULACION_REQUERIDO"
    mal = client.post(f"{API}/auth/register", json={**body, "codigo_vinculacion": "ZZZZZZZZ"})
    assert mal.status_code == 422 and mal.json()["code"] == "CODIGO_VINCULACION_INVALIDO"
    # un correo distinto con el código correcto tampoco sirve
    otro = client.post(f"{API}/auth/register", json={**body, "email": "intruso@example.com",
                                                     "codigo_vinculacion": aut["codigo_vinculacion"]})
    assert otro.status_code == 422
    ok = client.post(f"{API}/auth/register", json={**body, "codigo_vinculacion": aut["codigo_vinculacion"].lower()})
    assert ok.status_code == 201, ok.text
    h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    vistos = client.get(f"{API}/familiar/estudiantes", headers=h)
    assert vistos.status_code == 200 and len(vistos.json()) == 1
    lista = client.get(f"{API}/estudiantes/mi/familiares", headers=auth_headers(world.estudiante_user)).json()
    assert lista[0]["estado"] == "VIGENTE" and lista[0]["codigo_vinculacion"] is None


def test_familiar_ya_registrado_queda_vigente_al_instante(client, world):
    body = {"nombre": "Marta Pérez", "email": "marta@example.com", "alcance": {"plan": True}}
    h = auth_headers(world.estudiante_user)
    codigo = client.post(f"{API}/estudiantes/mi/familiares", headers=h, json=body).json()["codigo_vinculacion"]
    client.post(f"{API}/auth/register", json={"rol": "FAMILIAR", "nombre_completo": "Marta Pérez", "email": "marta@example.com",
                                              "password": CLAVE, "codigo_vinculacion": codigo, "acepta_aviso_privacidad": True})
    aut_id = client.get(f"{API}/estudiantes/mi/familiares", headers=h).json()[0]["id"]
    assert client.delete(f"{API}/estudiantes/mi/familiares/{aut_id}", headers=h).status_code == 200
    # al volver a autorizar a quien ya tiene cuenta, queda vigente sin pedir código
    otra = client.post(f"{API}/estudiantes/mi/familiares", headers=h, json=body).json()
    assert otra["estado"] == "VIGENTE" and otra["codigo_vinculacion"] is None
