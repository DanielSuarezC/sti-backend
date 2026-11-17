"""Middleware: cabeceras de seguridad (HSTS, etc.), request-id y CORS configurable."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings

_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        request.state.request_id = request.headers.get("x-request-id", uuid.uuid4().hex)[:50]
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Request-ID", request.state.request_id)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if not request.url.path.startswith(_DOC_PATHS):
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        # Respuestas con datos personales nunca deben cachearse
        if request.url.path.startswith(s.api_prefix):
            h.setdefault("Cache-Control", "no-store")
        hsts = s.hsts_enabled if s.hsts_enabled is not None else (s.is_production or s.cookie_secure)
        if hsts:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        return response


def install_middleware(app: FastAPI) -> None:
    s = get_settings()
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,  # cookie de refresh
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Jobs-Secret"],
        expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"],
        max_age=600,
    )
