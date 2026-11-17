"""Adaptador SSO OIDC/OAuth2 genérico (R5: fallback a autenticación local).

Configuración por variables de entorno (`SSO_*`): ver `.env.example`. Soporta *discovery*
(`{SSO_ISSUER}/.well-known/openid-configuration`) o endpoints explícitos. Flujo código de autorización:

    GET /auth/sso/login      -> 302 al proveedor (state firmado, 10 min)
    GET /auth/sso/callback   -> intercambia el código, lee el correo verificado, busca la cuenta EXISTENTE y emite
                                la sesión (cookie de refresh); redirige a `{FRONTEND_URL}/login?sso=ok`.

No hay aprovisionamiento automático: una persona sin cuenta (o sin solicitud aprobada) no entra. Si el proveedor
institucional es SAML/LDAP, se coloca un broker OIDC (Keycloak/Azure AD/Google) delante.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings
from app.core.errors import AppError, NotImplementedFeature
from app.core.security import _jwt_secret

logger = logging.getLogger("sti.sso")


@dataclass
class OIDCEndpoints:
    authorization: str
    token: str
    userinfo: str | None


def ensure_configured() -> None:
    if not get_settings().sso_configured:
        raise NotImplementedFeature(
            "El inicio de sesión institucional (SSO) aún no está configurado en este entorno. "
            "Use su correo y contraseña.",
            "SSO_NO_CONFIGURADO",
        )


_discovery_cache: dict[str, tuple[float, OIDCEndpoints]] = {}


def get_endpoints() -> OIDCEndpoints:
    s = get_settings()
    if s.sso_authorization_endpoint and s.sso_token_endpoint:
        return OIDCEndpoints(s.sso_authorization_endpoint, s.sso_token_endpoint, s.sso_userinfo_endpoint or None)
    cached = _discovery_cache.get(s.sso_issuer)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    url = s.sso_issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        doc = httpx.get(url, timeout=10).raise_for_status().json()
        ep = OIDCEndpoints(doc["authorization_endpoint"], doc["token_endpoint"], doc.get("userinfo_endpoint"))
    except Exception as exc:
        logger.warning("Fallo el discovery OIDC (%s): %s", url, exc)
        raise AppError("No fue posible contactar el servicio de inicio de sesión institucional. Intente más tarde.",
                       "SSO_NO_DISPONIBLE", status_code=503)
    _discovery_cache[s.sso_issuer] = (time.time(), ep)
    return ep


def build_login_url() -> str:
    ensure_configured()
    s = get_settings()
    ep = get_endpoints()
    state = jwt.encode({"nonce": uuid.uuid4().hex, "exp": int(time.time()) + 600, "typ": "sso_state"},
                       _jwt_secret(), algorithm="HS256")
    q = urlencode({
        "response_type": "code", "client_id": s.sso_client_id, "redirect_uri": s.sso_redirect_uri,
        "scope": s.sso_scopes, "state": state,
    })
    return f"{ep.authorization}?{q}"


def verify_state(state: str | None) -> None:
    try:
        payload = jwt.decode(state or "", _jwt_secret(), algorithms=["HS256"])
        if payload.get("typ") != "sso_state":
            raise ValueError
    except Exception:
        raise AppError("La solicitud de inicio de sesión institucional expiró o no es válida. Intente de nuevo.",
                       "SSO_STATE_INVALIDO", status_code=400)


def exchange_code_for_identity(code: str) -> dict:
    """Devuelve ``{"sub": ..., "email": ..., "email_verified": bool, "name": ...}`` del proveedor."""
    ensure_configured()
    s = get_settings()
    ep = get_endpoints()
    try:
        with httpx.Client(timeout=15) as client:
            tok = client.post(ep.token, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": s.sso_redirect_uri,
                "client_id": s.sso_client_id, "client_secret": s.sso_client_secret,
            }).raise_for_status().json()
            claims: dict = {}
            if ep.userinfo and tok.get("access_token"):
                claims = client.get(ep.userinfo, headers={"Authorization": f"Bearer {tok['access_token']}"}).raise_for_status().json()
            elif tok.get("id_token"):
                # El id_token llega por canal TLS directo desde el endpoint de token del proveedor.
                claims = jwt.decode(tok["id_token"], options={"verify_signature": False})
    except httpx.HTTPError as exc:
        logger.warning("Fallo el intercambio OIDC: %s", exc)
        raise AppError("No fue posible completar el inicio de sesión institucional. Intente de nuevo.",
                       "SSO_ERROR", status_code=502)
    if not claims.get("email"):
        raise AppError("El proveedor institucional no entregó un correo electrónico.", "SSO_SIN_CORREO", status_code=400)
    return {
        "sub": str(claims.get("sub") or claims["email"]),
        "email": str(claims["email"]).lower(),
        "email_verified": claims.get("email_verified", True) is not False,
        "name": claims.get("name"),
    }
