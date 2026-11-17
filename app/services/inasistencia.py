"""Monitoreo de inasistencia (RF-31, D15, R6): registro manual de Bienestar + lectura opcional del SIGAA.

# OWNER: slice C2

* Umbral: parametro `umbral_inasistencia` (PARAMETRO_SISTEMA, por defecto 20 %). Si porcentaje >= umbral se envia el correo
  inmediato `INASISTENCIA_UMBRAL` a Bienestar + Coordinador del programa, UNA vez por estudiante y periodo (semestre).
* SIGAA: desactivado por defecto. Se activa con `SIGAA_API_URL` (y opcional `SIGAA_API_TOKEN`); si no responde, la API
  indica registrar manualmente (R6: fallback manual).
"""

from __future__ import annotations

import logging
import os
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.errors import AppError, NotImplementedFeature
from app.models.academico import CalendarioAcademico, RegistroInasistencia
from app.models.usuarios import Estudiante, Usuario
from app.services import semaforo as sem
from app.services.notifications import Evento, notify
from app.services.params import get_param
from app.services.ruta import ruta_front

logger = logging.getLogger("sti.inasistencia")


class SigaaNoDisponible(AppError):
    status_code = 502
    default_code = "SIGAA_NO_DISPONIBLE"
    default_detail = "No pudimos consultar el SIGAA. Registre la inasistencia manualmente."


def umbral(db: Session) -> Decimal:
    return Decimal(str(get_param(db, "umbral_inasistencia", 20)))


def semestre_por_defecto(db: Session) -> str | None:
    cal = db.scalar(select(CalendarioAcademico).where(CalendarioAcademico.activo.is_(True)).order_by(CalendarioAcademico.id.desc()))
    return cal.semestre_academico if cal else None


def registrar(db: Session, est: Estudiante, actor: Usuario, datos: dict, *, fuente: str = "MANUAL", request=None) -> dict:
    semestre = datos.get("semestre_academico") or semestre_por_defecto(db)
    if not semestre:
        from app.core.errors import Unprocessable

        raise Unprocessable("Indique el semestre académico (no hay un calendario activo del cual tomarlo).", "SEMESTRE_REQUERIDO")
    pct = Decimal(str(datos["porcentaje_inasistencia"]))
    previa = db.scalar(select(RegistroInasistencia.id).where(
        RegistroInasistencia.estudiante_id == est.id, RegistroInasistencia.semestre_academico == semestre,
        RegistroInasistencia.alerta_generada.is_(True)))
    reg = RegistroInasistencia(
        estudiante_id=est.id, asignatura_id=datos.get("asignatura_id"), semestre_academico=semestre,
        fecha_registro=datos.get("fecha_registro") or date.today(), porcentaje_inasistencia=pct, fuente=fuente,
        observaciones=datos.get("observaciones"), registrado_por_id=actor.id,
    )
    db.add(reg)
    db.flush()
    lim = umbral(db)
    alerta = False
    if pct >= lim and previa is None:
        reg.alerta_generada = True
        alerta = True
        _alertar(db, est, actor, pct, lim, semestre)
    audit.log(db, actor, "INASISTENCIA_REGISTRADA", "registro_inasistencia", reg.id,
              {"porcentaje": float(pct), "semestre": semestre, "alerta": alerta, "fuente": fuente},
              request=request, estudiante_id=est.id)
    return {"registro": serializar(reg), "umbral": float(lim), "supera_umbral": pct >= lim, "alerta_enviada": alerta,
            "alerta_ya_enviada_en_el_periodo": bool(pct >= lim and previa is not None)}


def _alertar(db: Session, est: Estudiante, actor: Usuario, pct: Decimal, lim: Decimal, semestre: str) -> None:
    est_user = db.get(Usuario, est.usuario_id)
    b = sem.bienestar_responsable(db, est, None, actor)
    destinatarios: list[Usuario] = ([b] if b else []) + sem.coordinadores_del_programa(db, est.programa_id)
    if not destinatarios:
        return
    notify(db, Evento.INASISTENCIA_UMBRAL, destinatarios, {
        "estudiante_nombre": est_user.nombre_completo if est_user else "El estudiante", "porcentaje": f"{pct:.1f}",
        "umbral": f"{lim:.0f}", "enlace": ruta_front("BIENESTAR", "inasistencia", estudiante_id=est.id),
        "estudiante_id": est.id, "semestre": semestre,
    }, dedupe_key=f"inasistencia:{est.id}:{semestre}")


def serializar(r: RegistroInasistencia) -> dict:
    return {"id": r.id, "estudiante_id": r.estudiante_id, "asignatura_id": r.asignatura_id,
            "semestre_academico": r.semestre_academico, "fecha_registro": r.fecha_registro.isoformat(),
            "porcentaje_inasistencia": float(r.porcentaje_inasistencia), "fuente": str(r.fuente),
            "alerta_generada": r.alerta_generada, "observaciones": r.observaciones, "registrado_por_id": r.registrado_por_id}


def listar(db: Session, est_id: int) -> list[dict]:
    return [serializar(r) for r in db.scalars(select(RegistroInasistencia).where(
        RegistroInasistencia.estudiante_id == est_id).order_by(RegistroInasistencia.fecha_registro.desc(), RegistroInasistencia.id.desc()))]


# ----------------------------------------------------------------------------- SIGAA (opcional)
def sigaa_url() -> str | None:
    return getattr(get_settings(), "sigaa_api_url", None) or os.environ.get("SIGAA_API_URL") or None


def consultar_sigaa(codigo_estudiante: str, semestre: str | None) -> Decimal:
    """GET {SIGAA_API_URL}/inasistencia?codigo=..&semestre=.. -> {"porcentaje_inasistencia": 12.5}. Lanza 501 si esta apagado."""
    url = sigaa_url()
    if not url:
        raise NotImplementedFeature(
            "La conexión con el SIGAA no está activada en este despliegue. Registre la inasistencia manualmente.",
            "SIGAA_NO_CONFIGURADO")
    import httpx

    headers = {"Authorization": f"Bearer {os.environ['SIGAA_API_TOKEN']}"} if os.environ.get("SIGAA_API_TOKEN") else {}
    try:
        r = httpx.get(f"{url.rstrip('/')}/inasistencia", params={"codigo": codigo_estudiante, "semestre": semestre},
                      headers=headers, timeout=8.0)
        r.raise_for_status()
        return Decimal(str(r.json()["porcentaje_inasistencia"]))
    except Exception as exc:  # noqa: BLE001 - cualquier fallo => fallback manual (R6)
        logger.warning("SIGAA no disponible: %s", exc.__class__.__name__)
        raise SigaaNoDisponible() from exc
