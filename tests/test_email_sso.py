"""Envío SMTP (simulado) y flujo SSO OIDC (simulado)."""

import pytest
from sqlalchemy import select

from app.core import config
from app.models import EmailOutbox
from app.models.enums import Rol
from app.services import email as email_service
from app.services import sso
from app.services.notifications import Evento, notify
from tests.factories import make_user


@pytest.fixture()
def smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    config.reset_settings_cache()
    yield
    monkeypatch.setenv("SMTP_HOST", "")
    config.reset_settings_cache()


def test_email_outbox_sent_with_smtp(db, smtp_env, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "smtp_send", lambda to, subj, text, html=None: sent.append((to, subj)))
    monkeypatch.setattr("app.services.notifications.enqueue", lambda fn, *a, **k: None)  # sin hilos en la prueba
    b = make_user(db, Rol.BIENESTAR)
    notify(db, Evento.PLAN_FIRMADO_APROBADO, [b], {"version": 1, "enlace": "/x"})
    db.commit()
    row = db.scalar(select(EmailOutbox))
    assert row.estado == "PENDIENTE"  # con SMTP: se envía después del commit
    assert email_service.process_outbox(db) == 1
    db.refresh(row)
    assert row.estado == "ENVIADO" and row.enviado_at and sent == [(b.email, row.asunto)]


def test_email_retries_then_errors(db, smtp_env, monkeypatch):
    def boom(*a, **k):
        raise OSError("sin red")

    monkeypatch.setattr(email_service, "smtp_send", boom)
    monkeypatch.setattr("app.services.notifications.enqueue", lambda fn, *a, **k: None)
    b = make_user(db, Rol.BIENESTAR)
    notify(db, Evento.PLAN_FIRMADO_APROBADO, [b], {})
    db.commit()
    for _ in range(email_service.MAX_INTENTOS):
        email_service.process_outbox(db)
    row = db.scalar(select(EmailOutbox))
    assert row.estado == "ERROR" and row.intentos == email_service.MAX_INTENTOS and "sin red" in row.ultimo_error


@pytest.fixture()
def sso_env(monkeypatch):
    for k, v in {"SSO_ENABLED": "true", "SSO_CLIENT_ID": "cid", "SSO_CLIENT_SECRET": "sec",
                 "SSO_REDIRECT_URI": "http://localhost:8000/api/v1/auth/sso/callback",
                 "SSO_AUTHORIZATION_ENDPOINT": "https://idp.test/authorize", "SSO_TOKEN_ENDPOINT": "https://idp.test/token"}.items():
        monkeypatch.setenv(k, v)
    config.reset_settings_cache()
    yield
    for k in ("SSO_ENABLED", "SSO_CLIENT_ID", "SSO_CLIENT_SECRET", "SSO_REDIRECT_URI", "SSO_AUTHORIZATION_ENDPOINT",
              "SSO_TOKEN_ENDPOINT"):
        monkeypatch.delenv(k)
    config.reset_settings_cache()


def test_sso_login_redirect_and_callback(client, db, sso_env, monkeypatch):
    r = client.get("/api/v1/auth/sso/login", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://idp.test/authorize?")
    assert "client_id=cid" in r.headers["location"]
    state = r.headers["location"].split("state=")[1].split("&")[0]

    u = make_user(db, Rol.BIENESTAR, email="bienestar@unicordoba.test.example.com")
    monkeypatch.setattr(sso, "exchange_code_for_identity",
                        lambda code: {"sub": "abc", "email": u.email, "email_verified": True, "name": "X"})
    ok = client.get("/api/v1/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert ok.status_code == 302 and ok.headers["location"].endswith("/login?sso=ok")
    assert "sti_refresh" in ok.headers["set-cookie"]
    me = client.post("/api/v1/auth/refresh")  # el SPA obtiene el access token con la cookie
    assert me.status_code == 200 and me.json()["user"]["email"] == u.email

    monkeypatch.setattr(sso, "exchange_code_for_identity",
                        lambda code: {"sub": "zzz", "email": "nadie@example.com", "email_verified": True, "name": None})
    sin = client.get("/api/v1/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert sin.headers["location"].endswith("/login?sso=sin_cuenta")  # no hay aprovisionamiento automático
    bad = client.get("/api/v1/auth/sso/callback", params={"code": "c", "state": "falso"}, follow_redirects=False)
    assert bad.status_code == 400 and bad.json()["code"] == "SSO_STATE_INVALIDO"
