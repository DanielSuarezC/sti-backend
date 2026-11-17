"""Autenticación: login, bloqueo, refresh con rotación, activación (72 h), recuperación, /me, preferencias, SSO."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.models import LogAuditoria, RefreshToken, Usuario
from app.models.base import utcnow
from app.models.enums import EstadoUsuario, Rol
from app.services.accounts import create_user, invite_user
from tests.factories import PASSWORD, make_estudiante, make_programa, make_user


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_login_ok_shape(client, db):
    u = make_user(db, Rol.BIENESTAR, email="bienestar@example.com")
    r = _login(client, u.email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 3600
    me = body["user"]
    assert set(me) == {"id", "email", "nombre_completo", "rol", "estado", "consentimiento_firmado", "programa_id",
                       "preferencias_ui"}
    assert me["rol"] == "BIENESTAR" and me["consentimiento_firmado"] is True
    assert set(me["preferencias_ui"]) == {"modo_calma", "tamano_texto", "espaciado", "sin_movimiento",
                                          "alto_contraste", "fuente"}
    # cookie de refresh HttpOnly
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc and "path=/api/v1/auth" in sc
    # auditoría
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "LOGIN_OK"))


def test_login_wrong_password_and_unknown_user(client, db):
    u = make_user(db, Rol.BIENESTAR)
    r = _login(client, u.email, "incorrecta123")
    assert r.status_code == 401 and r.json()["code"] == "CREDENCIALES_INVALIDAS"
    r = _login(client, "nadie@example.com")
    assert r.status_code == 401 and r.json()["code"] == "CREDENCIALES_INVALIDAS"
    assert "detail" in r.json()


def test_lockout_after_5_attempts(client, db):
    u = make_user(db, Rol.BIENESTAR)
    for i in range(4):
        assert _login(client, u.email, "mala-clave-1").status_code == 401, i
    r5 = _login(client, u.email, "mala-clave-1")
    assert r5.status_code == 423 and r5.json()["code"] == "CUENTA_BLOQUEADA"
    # incluso con la contraseña correcta sigue bloqueada
    r6 = _login(client, u.email)
    assert r6.status_code == 423
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "LOGIN_BLOQUEO"))
    # vencido el bloqueo (15 min) puede entrar
    db.expire_all()
    user = db.get(Usuario, u.id)
    assert user.locked_until is not None
    assert (user.locked_until - utcnow()) <= timedelta(minutes=15)
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _login(client, u.email).status_code == 200
    db.expire_all()
    assert db.get(Usuario, u.id).failed_attempts == 0


def test_inactive_and_unactivated_cannot_login(client, db):
    u = make_user(db, Rol.DOCENTE, estado=EstadoUsuario.INACTIVO)
    assert _login(client, u.email).status_code == 403
    nuevo = create_user(db, email="nuevo@example.com", nombre_completo="Nuevo", rol=Rol.DOCENTE)
    db.commit()
    assert nuevo.estado == EstadoUsuario.PENDIENTE_ACTIVACION
    assert _login(client, "nuevo@example.com", PASSWORD).status_code == 401


def test_refresh_rotation_and_reuse_detection(client, db):
    u = make_user(db, Rol.BIENESTAR)
    assert _login(client, u.email).status_code == 200
    old = client.cookies.get("sti_refresh")
    assert old

    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    assert r.json()["access_token"] and r.json()["user"]["email"] == u.email
    new = client.cookies.get("sti_refresh")
    assert new and new != old  # rotó

    # reutilizar el token viejo => 401 y se revoca TODA la familia
    client.cookies.set("sti_refresh", old, path="/api/v1/auth")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_REUTILIZADO"
    client.cookies.set("sti_refresh", new, path="/api/v1/auth")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401  # el nuevo también quedó revocado (familia)
    db.expire_all()
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_refresh_without_cookie(client):
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_AUSENTE"


def test_logout_revokes_refresh(client, db):
    u = make_user(db, Rol.BIENESTAR)
    _login(client, u.email)
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    db.expire_all()
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_activation_flow_and_72h_expiry(client, db):
    s = get_settings()
    u = create_user(db, email="doc@example.com", nombre_completo="Doc Nuevo", rol=Rol.DOCENTE)
    raw = invite_user(db, u)
    db.commit()
    assert u.activation_expires_at is not None
    horas = (u.activation_expires_at - utcnow()).total_seconds() / 3600
    assert 71.9 < horas <= s.activation_token_hours == 72
    # el correo de invitación quedó en outbox (sin SMTP => OMITIDO) con el enlace
    from app.models import EmailOutbox

    box = db.scalar(select(EmailOutbox).where(EmailOutbox.destinatario_email == "doc@example.com"))
    assert box and raw in box.cuerpo_texto and box.estado == "OMITIDO"

    # contraseña débil
    r = client.post("/api/v1/auth/activate", json={"token": raw, "password": "corta"})
    assert r.status_code == 422 and r.json()["code"] == "CONTRASENA_DEBIL"
    # activación correcta
    r = client.post("/api/v1/auth/activate", json={"token": raw, "password": "NuevaClave2026"})
    assert r.status_code == 200 and r.json()["estado"] == "ACTIVO"
    assert _login(client, "doc@example.com", "NuevaClave2026").status_code == 200
    # el token no se puede reusar
    r = client.post("/api/v1/auth/activate", json={"token": raw, "password": "OtraClave2026"})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_ACTIVACION_INVALIDO"


def test_activation_token_expired_after_72h(client, db):
    u = create_user(db, email="viejo@example.com", nombre_completo="Viejo", rol=Rol.COORDINADOR)
    raw = invite_user(db, u)
    u.activation_expires_at = utcnow() - timedelta(hours=1)  # pasaron las 72 h
    db.commit()
    r = client.post("/api/v1/auth/activate", json={"token": raw, "password": "NuevaClave2026"})
    assert r.status_code == 400 and r.json()["code"] == "TOKEN_ACTIVACION_VENCIDO"
    assert "72" in r.json()["detail"]


def test_student_activation_goes_to_pending_consent(client, db):
    prog = make_programa(db)
    u = create_user(db, email="est@example.com", nombre_completo="Estu", rol=Rol.ESTUDIANTE,
                    perfil={"codigo_estudiante": "E1", "programa_id": prog.id})
    raw = invite_user(db, u)
    db.commit()
    r = client.post("/api/v1/auth/activate", json={"token": raw, "password": "NuevaClave2026"})
    assert r.json()["estado"] == "PENDIENTE_CONSENTIMIENTO"
    me = _login(client, "est@example.com", "NuevaClave2026").json()["user"]
    assert me["consentimiento_firmado"] is False and me["programa_id"] == prog.id


def test_forgot_and_reset_password(client, db):
    u = make_user(db, Rol.BIENESTAR, email="olvido@example.com")
    r = client.post("/api/v1/auth/forgot-password", json={"email": "olvido@example.com"})
    r2 = client.post("/api/v1/auth/forgot-password", json={"email": "noexiste@example.com"})
    assert r.status_code == r2.status_code == 200 and r.json() == r2.json()  # no revela existencia
    from app.models import EmailOutbox

    box = db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "RECUPERACION_CONTRASENA"))
    assert box is not None
    token = box.cuerpo_texto.split("token=")[1].split()[0]
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "x"}).status_code == 422
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "ClaveNueva2026"})
    assert r.status_code == 200
    assert _login(client, u.email, PASSWORD).status_code == 401
    assert _login(client, u.email, "ClaveNueva2026").status_code == 200
    assert client.post("/api/v1/auth/reset-password",
                       json={"token": token, "password": "ClaveNueva2027"}).status_code == 400


def test_me_requires_auth_and_returns_user(client, db):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer basura"}).json()["code"] == "TOKEN_INVALIDO"
    u = make_user(db, Rol.COORDINADOR, perfil={"programa_responsable_ids": [7]})
    token = _login(client, u.email).json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["id"] == u.id and me["programa_id"] == 7


def test_preferencias_patch(client, db):
    u = make_user(db, Rol.ESTUDIANTE, perfil={"codigo_estudiante": "E9"})
    token = _login(client, u.email).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.patch("/api/v1/auth/me/preferencias", headers=h,
                     json={"modo_calma": True, "tamano_texto": 115, "espaciado": "amplio", "fuente": "dyslexia"})
    assert r.status_code == 200, r.text
    p = r.json()["preferencias_ui"]
    assert p["modo_calma"] is True and p["tamano_texto"] == 115 and p["espaciado"] == "AMPLIO" and p["fuente"] == "DISLEXIA"
    assert client.get("/api/v1/auth/me", headers=h).json()["preferencias_ui"]["tamano_texto"] == 115
    r = client.patch("/api/v1/auth/me/preferencias", headers=h, json={"tamano_texto": 120})
    assert r.status_code == 422 and r.json()["code"] == "DATOS_INVALIDOS"
    # parcial: no pisa lo demás
    r = client.patch("/api/v1/auth/me/preferencias", headers=h, json={"alto_contraste": True})
    p = r.json()["preferencias_ui"]
    assert p["alto_contraste"] is True and p["tamano_texto"] == 115


def test_expired_access_token_rejected(client, db):
    import jwt

    from app.core.security import _jwt_secret

    u = make_user(db, Rol.BIENESTAR)
    tok = jwt.encode({"sub": str(u.id), "typ": "access", "exp": int((utcnow() - timedelta(minutes=1)).timestamp())},
                     _jwt_secret(), algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRADO"


def test_sso_not_configured_returns_501(client):
    r = client.get("/api/v1/auth/sso/login", follow_redirects=False)
    assert r.status_code == 501 and r.json()["code"] == "SSO_NO_CONFIGURADO"
    assert client.get("/api/v1/auth/sso/callback", follow_redirects=False).status_code == 501


def test_student_without_consent_can_login(client, db):
    prog = make_programa(db)
    u, _ = make_estudiante(db, prog, consent=False)
    r = _login(client, u.email)
    assert r.status_code == 200 and r.json()["user"]["consentimiento_firmado"] is False
    assert r.json()["user"]["estado"] == "PENDIENTE_CONSENTIMIENTO"
