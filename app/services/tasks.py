"""Cola de tareas con degradación: Celery si hay `CELERY_BROKER_URL`; si no, en línea (pruebas) o en un hilo.

Registro de tareas::

    @task("exportar_plan")
    def exportar_plan(exportacion_id: int) -> None: ...

    enqueue(exportar_plan, exportacion_id)          # no bloquea la petición

Reglas para las funciones de tarea: argumentos serializables (ids, no objetos ORM) y abrir su propia sesión con
``session_scope()``. `enqueue` nunca lanza: los errores se registran (las notificaciones no deben romper la
operación de negocio, M10).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("sti.tasks")

_REGISTRY: dict[str, Callable[..., Any]] = {}


def task(name: str | None = None):
    """Registra una función como tarea (nombre Celery `sti.<name>`)."""

    def deco(fn):
        task_name = name or fn.__name__
        fn.task_name = task_name
        _REGISTRY[task_name] = fn
        return fn

    return deco


def registered_tasks() -> dict[str, Callable[..., Any]]:
    return dict(_REGISTRY)


def _run_safely(fn, args, kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("Falló la tarea %s", getattr(fn, "__name__", fn))


def enqueue(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Encola `fn`. Devuelve el modo usado: 'celery', 'inline' o 'thread'."""
    s = get_settings()
    name = getattr(fn, "task_name", None)
    if s.celery_broker_url and name:
        try:
            from app.workers.celery_app import celery_app

            if celery_app is not None:
                celery_app.send_task(f"sti.{name}", args=list(args), kwargs=kwargs)
                return "celery"
        except Exception:
            logger.exception("No se pudo encolar en Celery; se ejecuta localmente")
    if s.is_test:
        _run_safely(fn, args, kwargs)
        return "inline"
    threading.Thread(target=_run_safely, args=(fn, args, kwargs), daemon=True, name=f"sti-task-{name or 'anon'}").start()
    return "thread"
