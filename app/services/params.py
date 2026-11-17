"""Acceso tipado a PARAMETRO_SISTEMA (configuración editable por el Administrador, M1) con valores por defecto."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import TipoParametro
from app.models.sistema import ParametroSistema

#: clave -> (valor por defecto, tipo, descripcion)
DEFAULTS: dict[str, tuple[Any, TipoParametro, str]] = {
    "aq10_punto_corte": (6, TipoParametro.ENTERO, "Puntaje AQ-10 desde el cual se activa la ruta MAAR-TEA (>=)."),
    "umbral_inasistencia": (20, TipoParametro.DECIMAL, "Porcentaje de inasistencia que dispara alerta (RAE)."),
    "max_ciclos_negociacion": (3, TipoParametro.ENTERO, "Ciclos de negociación antes de escalar al Comité (RF-25)."),
    "dias_purga_sin_consentimiento": (30, TipoParametro.ENTERO, "Días tras los que se purgan cuentas sin F0."),
    "dias_recordatorio_corte_email": (7, TipoParametro.ENTERO, "Días antes del corte para el correo de recordatorio."),
    "dias_recordatorio_corte_push": (1, TipoParametro.ENTERO, "Días antes del corte para la notificación push."),
    "version_texto_f0": ("F0-v1", TipoParametro.TEXTO, "Versión vigente del texto del consentimiento informado."),
    "comite_inclusion_email": ("", TipoParametro.TEXTO, "Correo del Comité de Inclusión (escalamiento RF-25)."),
}


def get_param(db: Session, clave: str, default: Any = None) -> Any:
    row = db.scalar(select(ParametroSistema).where(ParametroSistema.clave == clave))
    if row is not None and row.valor is not None:
        return row.valor
    if default is not None:
        return default
    return DEFAULTS.get(clave, (None,))[0]


def set_param(db: Session, clave: str, valor: Any, *, descripcion: str | None = None) -> ParametroSistema:
    row = db.scalar(select(ParametroSistema).where(ParametroSistema.clave == clave))
    d = DEFAULTS.get(clave)
    if row is None:
        row = ParametroSistema(
            clave=clave, valor=valor, tipo=d[1] if d else TipoParametro.TEXTO,
            descripcion=descripcion or (d[2] if d else None),
        )
        db.add(row)
    else:
        row.valor = valor
    db.flush()
    return row


def ensure_defaults(db: Session) -> int:
    """Inserta los parámetros que falten (idempotente). Devuelve cuántos creó."""
    existing = set(db.scalars(select(ParametroSistema.clave)))
    n = 0
    for clave, (valor, tipo, desc) in DEFAULTS.items():
        if clave not in existing:
            db.add(ParametroSistema(clave=clave, valor=valor, tipo=tipo, descripcion=desc))
            n += 1
    db.flush()
    return n
