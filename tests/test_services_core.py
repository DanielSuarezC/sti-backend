"""Notificaciones, tareas, almacenamiento, errores, paginación, cabeceras de seguridad y máquina de estados."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.models import EmailOutbox, LogAuditoria, Notificacion
from app.models.enums import Rol
from app.services import params, storage
from app.services.notifications import CATALOGO, Evento, notify, render
from app.services.plan_states import TRANSICIONES, assert_transition, can_transition
from app.services.tasks import enqueue, task
from tests.factories import auth_headers, make_user


def test_catalog_covers_every_event():
    assert set(CATALOGO) == set(Evento)
    for ev, t in CATALOGO.items():
        assert t.titulo and t.asunto and t.cuerpo and t.canales, ev


def test_notify_creates_push_and_email_outbox(db):
    b = make_user(db, Rol.BIENESTAR)
    e = make_user(db, Rol.ESTUDIANTE, perfil={"codigo_estudiante": "E1"})
    n = notify(db, Evento.AJUSTE_SEMAFORO_ROJO, [b, e, b.id], {"ajuste": "Tiempo extra", "corte": "C2",
                                                              "enlace": "/bienestar/planes/3"})
    db.commit()
    assert len(n) == 2  # dedupe de destinatarios (b repetido)
    notifs = db.scalars(select(Notificacion)).all()
    assert {x.usuario_id for x in notifs} == {b.id, e.id}
    assert all(x.tipo == "AJUSTE_SEMAFORO_ROJO" and not x.leida and x.enlace == "/bienestar/planes/3" for x in notifs)
    assert "Tiempo extra" in notifs[0].mensaje and "C2" in notifs[0].titulo + notifs[0].mensaje
    boxes = db.scalars(select(EmailOutbox)).all()
    assert len(boxes) == 2 and all(x.estado == "OMITIDO" for x in boxes)  # sin SMTP: queda en outbox
    assert "http" in boxes[0].cuerpo_texto  # enlace absoluto en el correo
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "NOTIFICACION_ENVIADA"))


def test_notify_channels_override_and_dedupe(db):
    b = make_user(db, Rol.BIENESTAR)
    notify(db, Evento.RECORDATORIO_CORTE_7D, [b], {"corte": "C1", "fecha_corte": "2026-09-20", "semestre": "2026-II"},
           dedupe_key="corte:C1:2026-II:7d")
    notify(db, Evento.RECORDATORIO_CORTE_7D, [b], {"corte": "C1"}, dedupe_key="corte:C1:2026-II:7d")
    db.commit()
    assert len(db.scalars(select(EmailOutbox)).all()) == 1  # el segundo se omitió (idempotente)
    assert db.scalars(select(Notificacion)).all() == []  # 7 días = solo correo
    notify(db, Evento.RECORDATORIO_CORTE_1D, [b], {"corte": "C1"}, canales=["PUSH", "EMAIL"])
    db.commit()
    assert len(db.scalars(select(Notificacion)).all()) == 1


def test_render_tolerates_missing_vars():
    t, a, c, link = render(Evento.PLAN_LISTO_FIRMA, {})
    assert "{" not in a + c
    assert link is None


def test_enqueue_runs_inline_in_tests():
    box = []

    @task("t_demo")
    def demo(x):
        box.append(x)

    assert enqueue(demo, 5) == "inline" and box == [5]

    @task("t_fail")
    def boom():
        raise RuntimeError("x")

    assert enqueue(boom) == "inline"  # no propaga


def test_local_storage_roundtrip_and_traversal(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    config.reset_settings_cache()
    storage.reset_storage()
    try:
        key = storage.build_key("exportaciones", "../../evil plan.pdf")
        assert ".." not in key and key.startswith("exportaciones/")
        storage.put(key, b"%PDF-demo", "application/pdf")
        assert storage.exists(key) and storage.get(key) == b"%PDF-demo"
        resp = storage.download_response(key, "plan.pdf", "application/pdf")
        assert resp.body == b"%PDF-demo" and "attachment" in resp.headers["content-disposition"]
        with pytest.raises(ValueError):
            storage.get_storage()._path("../fuera.txt")
        storage.delete(key)
        assert not storage.exists(key)
    finally:
        monkeypatch.setenv("STORAGE_DIR", str(config.BASE_DIR / "tests" / ".storage_tmp"))
        config.reset_settings_cache()
        storage.reset_storage()


def test_params_defaults_and_override(db):
    assert params.get_param(db, "aq10_punto_corte") == 6
    assert params.get_param(db, "umbral_inasistencia") == 20
    params.set_param(db, "aq10_punto_corte", 7)
    assert params.get_param(db, "aq10_punto_corte") == 7
    assert params.ensure_defaults(db) == len(params.DEFAULTS) - 1


def test_plan_state_machine():
    assert can_transition("BORRADOR", "EN_CONCERTACION")
    assert not can_transition("BORRADOR", "APROBADO")
    assert_transition("PENDIENTE_FIRMAS", "APROBADO")
    with pytest.raises(Conflict) as ei:
        assert_transition("APROBADO", "BORRADOR")
    assert ei.value.code == "TRANSICION_PLAN_INVALIDA"
    assert TRANSICIONES["ARCHIVADO"] == ()
    assert "ESCALADO_COMITE" in [t.value for t in TRANSICIONES["EN_NEGOCIACION"]]


# ------------------------------------------------------------------ errores / paginación / cabeceras
def test_error_format_404_401_422(client, db):
    r = client.get("/api/v1/no-existe")
    assert r.status_code == 404 and set(r.json()) >= {"detail", "code"} and r.json()["code"] == "NO_ENCONTRADO"
    r = client.post("/api/v1/auth/login", json={"email": "no-es-correo", "password": ""})
    assert r.status_code == 422 and r.json()["code"] == "DATOS_INVALIDOS" and r.json()["errores"]
    assert "email" in r.json()["detail"]
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"


def test_pagination(client, db):
    for _ in range(5):
        make_user(db, Rol.BIENESTAR)
    r = client.get("/_t/usuarios", params={"page": 2, "page_size": 2}).json()
    assert r["total"] == 5 and r["page"] == 2 and r["page_size"] == 2 and len(r["items"]) == 2
    assert client.get("/_t/usuarios", params={"page_size": 1000}).status_code == 422
    assert client.get("/_t/usuarios", params={"page": 0}).status_code == 422


def test_security_headers_and_cors(client):
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "default-src 'none'" in h["content-security-policy"]
    assert h["access-control-allow-origin"] == "http://localhost:5173"
    assert h["access-control-allow-credentials"] == "true"
    assert "x-request-id" in h
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"
    bad = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_hsts_in_production(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config

    monkeypatch.setenv("HSTS_ENABLED", "true")
    config.reset_settings_cache()
    try:
        from app.main import create_app

        with TestClient(create_app()) as c:
            assert "max-age=63072000" in c.get("/health").headers["strict-transport-security"]
    finally:
        monkeypatch.delenv("HSTS_ENABLED")
        config.reset_settings_cache()


def test_login_rate_limit(client, db, monkeypatch):
    from app.core import config
    from app.core.ratelimit import reset_rate_limits

    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "3")
    config.reset_settings_cache()
    reset_rate_limits()
    try:
        codes = [client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"}).status_code
                 for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    finally:
        monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "0")
        config.reset_settings_cache()
        reset_rate_limits()


def test_ai_privacy_not_in_base():
    """RF-16/D4: solo `services/ai_gateway.py` puede referirse a openai/langchain; ningún otro módulo."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for f in root.rglob("*.py"):
        if f.name == "ai_gateway.py":
            continue
        src = f.read_text(encoding="utf-8")
        assert "import openai" not in src and "langchain" not in src, f


def test_auth_headers_helper(db):
    u = make_user(db, Rol.ADMIN)
    assert auth_headers(u)["Authorization"].startswith("Bearer ")
