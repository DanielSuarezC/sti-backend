"""Utilidades compartidas por el slice B (semestres, días hábiles, nombres, volcado de filas, acciones de auditoría)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core import audit
from app.models.base import utcnow
from app.models.usuarios import Usuario


class AccionB:
    """Acciones de auditoría propias del slice B (`audit.Accion` se reutiliza para las ya catalogadas)."""

    ARCO_SOLICITUD = "ARCO_SOLICITUD_RADICADA"
    ARCO_GESTION = "ARCO_SOLICITUD_GESTIONADA"
    ARCO_EXPORTACION = "ARCO_EXPORTACION_DATOS"
    CONSENTIMIENTO_CONSULTADO = "CONSENTIMIENTO_CONSULTADO"
    AQ10_FLUJO_ACTIVADO = "AQ10_FLUJO_ACTIVADO"
    ACCESO_AQ10 = audit.Accion.ACCESO_AQ10
    ACCESO_F1 = audit.Accion.ACCESO_CARACTERIZACION
    ACCESO_F2 = "ACCESO_PERFIL_FORTALEZAS"
    ESCRITURA_F1 = "CARACTERIZACION_MODIFICADA"
    ESCRITURA_F2 = "PERFIL_FORTALEZAS_MODIFICADO"
    FORMATO_CONFIRMADO = "FORMATO_CONFIRMADO"
    SUGERENCIAS_GENERADAS = "SUGERENCIAS_DUA_GENERADAS"
    SUGERENCIA_ACEPTADA = "SUGERENCIA_DUA_ACEPTADA"
    SUGERENCIA_MODIFICADA = "SUGERENCIA_DUA_MODIFICADA"
    SUGERENCIA_RECHAZADA = "SUGERENCIA_DUA_RECHAZADA"
    TEXTO_ACCESIBLE = "SUGERENCIA_DUA_TEXTO_ACCESIBLE"
    BARRERA_CREADA = "BARRERA_CREADA"
    BARRERA_MODIFICADA = "BARRERA_MODIFICADA"
    BARRERA_ELIMINADA = "BARRERA_ARCHIVADA"
    BARRERA_PERSISTENTE = "BARRERA_PERSISTENTE"
    FACILITADOR_CREADO = "FACILITADOR_CREADO"
    FACILITADOR_MODIFICADO = "FACILITADOR_MODIFICADO"
    FACILITADOR_ELIMINADO = "FACILITADOR_ARCHIVADO"
    CONTEXTO_MODIFICADO = "CONTEXTO_MODIFICADO"


# ------------------------------------------------------------------ semestres
_SEM_RE = re.compile(r"^(\d{4})-(I|II)$")


def semestre_valido(s: str) -> bool:
    return bool(_SEM_RE.match(s or ""))


def semestre_de(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.year}-{'I' if d.month <= 6 else 'II'}"


def semestre_anterior(sem: str) -> str:
    m = _SEM_RE.match(sem)
    if not m:
        raise ValueError(sem)
    year, half = int(m.group(1)), m.group(2)
    return f"{year}-I" if half == "II" else f"{year - 1}-II"


# ------------------------------------------------------------------ plazos (días hábiles)
def add_business_days(start: date, n: int) -> date:
    """Suma `n` días hábiles (lunes a viernes). No descuenta festivos colombianos: el plazo calculado nunca es
    más largo que el legal (criterio conservador)."""
    d = start
    left = n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


# ------------------------------------------------------------------ nombres
def normalize_name(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def name_matches(typed: str, account_name: str) -> bool:
    """El nombre tecleado debe corresponder a la cuenta: todas sus palabras están en el nombre de la cuenta y tiene al
    menos dos palabras (o todas, si la cuenta solo tiene una). Ignora tildes, mayúsculas y orden."""
    t, a = normalize_name(typed), set(normalize_name(account_name))
    if not t or not a:
        return False
    need = min(2, len(a))
    return len(t) >= need and all(tok in a for tok in t)


# ------------------------------------------------------------------ filas
_ROW_EXCLUDE = {"deleted_at", "deleted_reason", "deleted_by_id"}


def row_to_dict(obj: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    ex = _ROW_EXCLUDE | (exclude or set())
    return {c.key: jsonable_encoder(getattr(obj, c.key)) for c in obj.__table__.columns if c.key not in ex}


def soft_delete_obj(obj: Any, actor: Usuario | None, reason: str) -> None:
    obj.soft_delete(actor.id if actor else None, reason[:500])


def touch(obj: Any) -> None:
    obj.updated_at = utcnow()


