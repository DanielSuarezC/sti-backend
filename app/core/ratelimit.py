"""Rate limit simple en memoria (ventana deslizante) para login. En despliegues con varias instancias,
complementar con el límite del proxy/Cloudflare; el bloqueo por cuenta (5 intentos) sí es compartido (BD)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.audit import client_ip
from app.core.config import get_settings
from app.core.errors import TooManyRequests

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    if limit <= 0:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window_seconds - (now - q[0])))
            raise TooManyRequests(
                f"Demasiados intentos. Espere {retry} segundo(s) e intente de nuevo.",
                "DEMASIADOS_INTENTOS",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


def login_rate_limit(request: Request) -> None:
    """Dependencia FastAPI: límite por IP en endpoints de autenticación."""
    check_rate_limit(f"login:{client_ip(request) or 'desconocida'}", get_settings().login_rate_limit_per_minute)
