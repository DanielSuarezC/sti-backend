"""Panel de salud del sistema (M1, RF-38): BD, versión, conteos, últimos errores y cola de correo."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.base import utcnow
from app.models.enums import EstadoEmail, EstadoPlanEnum, EstadoUsuario
from app.models.plan import PlanMaarTea
from app.models.sistema import EmailOutbox, LogAuditoria, Notificacion
from app.models.usuarios import Usuario

_errores: deque[dict[str, Any]] = deque(maxlen=50)


class _ErrorBuffer(logging.Handler):
    """Guarda en memoria los últimos errores (solo mensaje corto, sin trazas ni datos de la petición)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _errores.appendleft({"fecha": utcnow().isoformat(), "origen": record.name, "mensaje": record.getMessage()[:300]})
        except Exception:  # noqa: BLE001
            pass


_handler = _ErrorBuffer(level=logging.ERROR)
if not any(isinstance(h, _ErrorBuffer) for h in logging.getLogger().handlers):
    logging.getLogger().addHandler(_handler)


def recent_errors(limit: int = 10) -> list[dict[str, Any]]:
    return list(_errores)[:limit]


def collect_health(db: Session) -> dict[str, Any]:
    s = get_settings()
    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        bd = {"ok": True, "motor": "sqlite" if s.is_sqlite else "postgresql",
              "latencia_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        bd = {"ok": False, "motor": "sqlite" if s.is_sqlite else "postgresql", "error": str(exc)[:200]}
    cola = {"pendientes": 0, "fallidas": 0, "omitidas": 0, "enviadas_24h": 0, "ultimos_errores": []}
    conteos: dict[str, int] = {}
    ultimo_job = None
    if bd["ok"]:
        por_estado = dict(db.execute(select(EmailOutbox.estado, func.count()).group_by(EmailOutbox.estado)).all())
        cola["pendientes"] = int(por_estado.get(EstadoEmail.PENDIENTE, 0))
        cola["fallidas"] = int(por_estado.get(EstadoEmail.ERROR, 0))
        cola["omitidas"] = int(por_estado.get(EstadoEmail.OMITIDO, 0))
        cola["enviadas_24h"] = int(db.scalar(select(func.count()).select_from(EmailOutbox).where(
            EmailOutbox.estado == EstadoEmail.ENVIADO, EmailOutbox.enviado_at >= utcnow() - timedelta(hours=24))) or 0)
        cola["ultimos_errores"] = [
            {"id": r.id, "asunto": r.asunto, "intentos": r.intentos, "error": (r.ultimo_error or "")[:200]}
            for r in db.scalars(select(EmailOutbox).where(EmailOutbox.estado == EstadoEmail.ERROR)
                                .order_by(EmailOutbox.id.desc()).limit(5))
        ]
        conteos = {
            "usuarios_activos": int(db.scalar(select(func.count()).select_from(Usuario).where(
                Usuario.estado == EstadoUsuario.ACTIVO)) or 0),
            "usuarios_pendientes": int(db.scalar(select(func.count()).select_from(Usuario).where(
                Usuario.estado.in_([EstadoUsuario.PENDIENTE_ACTIVACION, EstadoUsuario.PENDIENTE_CONSENTIMIENTO]))) or 0),
            "planes_vigentes": int(db.scalar(select(func.count()).select_from(PlanMaarTea).where(
                PlanMaarTea.estado.in_([EstadoPlanEnum.APROBADO, EstadoPlanEnum.IMPLEMENTACION,
                                        EstadoPlanEnum.SEGUIMIENTO]))) or 0),
            "notificaciones_no_leidas": int(db.scalar(select(func.count()).select_from(Notificacion).where(
                Notificacion.leida.is_(False))) or 0),
            "registros_auditoria": int(db.scalar(select(func.count()).select_from(LogAuditoria)) or 0),
        }
        job = db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "JOBS_DIARIOS_EJECUTADOS")
                        .order_by(LogAuditoria.id.desc()).limit(1))
        if job is not None:
            ultimo_job = {"fecha": job.created_at.isoformat(), "errores": (job.detalle or {}).get("errores", 0)}
    ok = bd["ok"]
    return {
        "status": "ok" if ok and cola["fallidas"] == 0 else "degradado",
        "version": s.app_version, "entorno": s.app_env, "base_de_datos": bd, "conteos": conteos,
        "cola_email": cola, "ultimos_errores": recent_errors(),
        "tareas": {"modo": "celery" if s.celery_broker_url else "en_linea", "broker_configurado": bool(s.celery_broker_url),
                   "ultimo_job_diario": ultimo_job, "jobs_secret_configurado": bool(s.jobs_secret)},
        "correo": "smtp" if s.smtp_configured else "outbox",
        "almacenamiento": "r2" if s.r2_configured else "disco_local",
        "generado_at": utcnow().isoformat(),
    }
