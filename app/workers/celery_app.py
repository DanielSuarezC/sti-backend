"""Aplicación Celery (solo se crea si hay `CELERY_BROKER_URL`).

Arranque del worker:   celery -A app.workers.celery_app.celery_app worker -l info
Arranque del programador (beat):   celery -A app.workers.celery_app.celery_app beat -l info
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("sti.celery")

celery_app = None


def _build():
    s = get_settings()
    if not s.celery_broker_url:
        return None
    try:
        from celery import Celery
        from celery.schedules import crontab
    except Exception:  # pragma: no cover - celery no instalado
        logger.warning("Celery no está instalado; las tareas se ejecutan sin cola.")
        return None

    app = Celery("sti", broker=s.celery_broker_url, backend=s.celery_result_backend or None)
    app.conf.update(
        timezone="America/Bogota",
        enable_utc=True,
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        beat_schedule={
            "sti-run-daily-jobs": {"task": "sti.run_daily_jobs_task", "schedule": crontab(hour=6, minute=0)},
            "sti-process-email-outbox": {"task": "sti.process_email_outbox_task", "schedule": 300.0},
        },
    )

    # Importa módulos con @task para registrarlos y expone cada uno como tarea Celery `sti.<nombre>`
    from app.services import jobs, notifications  # noqa: F401
    from app.services.tasks import registered_tasks

    for name, fn in registered_tasks().items():
        app.task(name=f"sti.{name}")(fn)
    return app


celery_app = _build()
