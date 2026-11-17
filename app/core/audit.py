"""Auditoría (RF-38): ``audit.log(db, actor, accion, entidad, entidad_id, detalle)``.

`LOG_AUDITORIA` es de solo anexo (protección ORM + trigger en PostgreSQL). `log()` solo agrega la fila a la
sesión: se confirma junto con la operación de negocio (si esa operación falla, no queda traza falsa).
Para eventos que deben persistir aunque la operación falle (login fallido, lockout) use ``commit=True``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.sistema import LogAuditoria
from app.models.usuarios import Usuario

# Claves que nunca deben quedar en el detalle (se enmascaran).
_SENSITIVE_KEYS = ("password", "contrasena", "token", "secret", "respuestas", "puntaje", "diagnostico")


class Accion:
    """Catálogo de acciones auditables (no es exhaustivo: `accion` es texto libre en snake/UPPER)."""

    LOGIN_OK = "LOGIN_OK"
    LOGIN_FALLIDO = "LOGIN_FALLIDO"
    LOGIN_BLOQUEO = "LOGIN_BLOQUEO"
    LOGOUT = "LOGOUT"
    ACTIVACION_CUENTA = "ACTIVACION_CUENTA"
    RECUPERACION_SOLICITADA = "RECUPERACION_SOLICITADA"
    CONTRASENA_RESTABLECIDA = "CONTRASENA_RESTABLECIDA"
    REFRESH_REUTILIZADO = "REFRESH_REUTILIZADO"
    CONSENTIMIENTO_FIRMADO = "CONSENTIMIENTO_FIRMADO"
    CONSENTIMIENTO_REVOCADO = "CONSENTIMIENTO_REVOCADO"
    ACCESO_AQ10 = "ACCESO_AQ10"
    APLICACION_AQ10 = "APLICACION_AQ10"
    ACCESO_CARACTERIZACION = "ACCESO_CARACTERIZACION"
    ACCESO_NOTAS_CONTINUIDAD = "ACCESO_NOTAS_CONTINUIDAD"
    ACCESO_DATO_SENSIBLE = "ACCESO_DATO_SENSIBLE"
    FIRMA_PLAN = "FIRMA_PLAN"
    CAMBIO_SEMAFORO = "CAMBIO_SEMAFORO"
    NOTIFICACION_ENVIADA = "NOTIFICACION_ENVIADA"
    EXPORTACION_SOLICITADA = "EXPORTACION_SOLICITADA"
    EXPORTACION_DESCARGADA = "EXPORTACION_DESCARGADA"
    AUTORIZACION_FAMILIAR_OTORGADA = "AUTORIZACION_FAMILIAR_OTORGADA"
    AUTORIZACION_FAMILIAR_REVOCADA = "AUTORIZACION_FAMILIAR_REVOCADA"
    USUARIO_CREADO = "USUARIO_CREADO"
    USUARIO_MODIFICADO = "USUARIO_MODIFICADO"
    PURGA_CUENTAS_SIN_CONSENTIMIENTO = "PURGA_CUENTAS_SIN_CONSENTIMIENTO"


def sanitize(detalle: Any) -> Any:
    if isinstance(detalle, dict):
        out = {}
        for k, v in detalle.items():
            if any(s in str(k).lower() for s in _SENSITIVE_KEYS):
                out[k] = "***"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(detalle, (list, tuple)):
        return [sanitize(v) for v in detalle]
    if isinstance(detalle, (str, int, float, bool)) or detalle is None:
        return detalle
    return str(detalle)


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:50]
    return request.client.host[:50] if request.client else None


def log(
    db: Session,
    actor: Usuario | None,
    accion: str,
    entidad: str | None = None,
    entidad_id: int | None = None,
    detalle: dict | None = None,
    *,
    request: Request | None = None,
    estudiante_id: int | None = None,
    actor_id: int | None = None,
    actor_rol: str | None = None,
    commit: bool = False,
) -> LogAuditoria:
    entry = LogAuditoria(
        actor_id=actor.id if actor is not None else actor_id,
        actor_rol=str(actor.rol) if actor is not None else actor_rol,
        accion=str(accion),
        entidad=entidad,
        entidad_id=entidad_id,
        estudiante_id=estudiante_id,
        detalle=sanitize(detalle) if detalle else None,
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] or None) if request is not None else None,
        request_id=getattr(request.state, "request_id", None) if request is not None else None,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry
