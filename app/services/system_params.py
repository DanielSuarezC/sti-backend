"""Parámetros del sistema editables por el Administrador (M1) con validación y auditoría de cambios.

Complementa `services/params.py` (que define los valores por defecto base) con los parámetros propios del slice A y
con las reglas de validación de cada clave. Solo se pueden editar las claves registradas aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import NotFound, Unprocessable
from app.models.enums import TipoParametro
from app.models.sistema import ParametroSistema
from app.models.usuarios import Usuario
from app.services import aq10_config, params

K_MINIMO_ABSOLUTO = 3  # el parámetro de k-anonimato nunca puede bajar de 3 (RF-36)


@dataclass(frozen=True)
class Spec:
    clave: str
    tipo: TipoParametro
    default: Any
    descripcion: str
    minimo: float | None = None
    maximo: float | None = None
    max_len: int | None = None
    email: bool = False


#: parámetros propios del slice A (los demás vienen de `params.DEFAULTS`)
EXTRA: dict[str, Spec] = {
    "reportes_k_minimo": Spec(
        "reportes_k_minimo", TipoParametro.ENTERO, K_MINIMO_ABSOLUTO,
        "Mínimo de personas por celda en reportes (k-anonimato). Las celdas con menos casos se ocultan.", 3, 20),
    "dias_negociacion_estancada": Spec(
        "dias_negociacion_estancada", TipoParametro.ENTERO, 7,
        "Días sin movimiento tras los que una negociación del plan se considera estancada (alerta a Bienestar).", 1, 90),
    "dias_ventana_f3_inicio_semestre": Spec(
        "dias_ventana_f3_inicio_semestre", TipoParametro.ENTERO, 14,
        "Días desde el inicio del semestre durante los que se recuerda el F3 pendiente.", 1, 60),
    aq10_config.PARAM_INSTRUCCIONES: Spec(
        aq10_config.PARAM_INSTRUCCIONES, TipoParametro.TEXTO, aq10_config.INSTRUCCIONES_POR_DEFECTO,
        "Texto de instrucciones del AQ-10 (también editable en /admin/aq10).", max_len=2000),
}

#: validación de los parámetros base de `params.DEFAULTS`
BASE_RULES: dict[str, dict[str, Any]] = {
    "aq10_punto_corte": {"minimo": 1, "maximo": 10},
    "umbral_inasistencia": {"minimo": 1, "maximo": 100},
    "max_ciclos_negociacion": {"minimo": 1, "maximo": 3},
    "dias_purga_sin_consentimiento": {"minimo": 7, "maximo": 365},
    "dias_recordatorio_corte_email": {"minimo": 1, "maximo": 30},
    "dias_recordatorio_corte_push": {"minimo": 1, "maximo": 14},
    "version_texto_f0": {"max_len": 20},
    "comite_inclusion_email": {"email": True, "max_len": 255},
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def specs() -> dict[str, Spec]:
    out: dict[str, Spec] = dict(EXTRA)
    for clave, (valor, tipo, desc) in params.DEFAULTS.items():
        rules = BASE_RULES.get(clave, {})
        out[clave] = Spec(clave, tipo, valor, desc, rules.get("minimo"), rules.get("maximo"), rules.get("max_len"),
                          rules.get("email", False))
    return out


def get_spec(clave: str) -> Spec:
    spec = specs().get(clave)
    if spec is None:
        raise NotFound(f"El parámetro «{clave}» no existe o no se puede editar.", "PARAMETRO_DESCONOCIDO")
    return spec


def get_value(db: Session, clave: str) -> Any:
    spec = get_spec(clave)
    return params.get_param(db, clave, spec.default)


def k_minimo(db: Session) -> int:
    try:
        return max(K_MINIMO_ABSOLUTO, int(get_value(db, "reportes_k_minimo")))
    except (TypeError, ValueError):
        return K_MINIMO_ABSOLUTO


def validate_value(spec: Spec, valor: Any) -> Any:
    def bad(msg: str) -> Unprocessable:
        return Unprocessable(f"{spec.clave}: {msg}", "PARAMETRO_INVALIDO")

    if spec.tipo == TipoParametro.ENTERO:
        if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
            raise bad("debe ser un número entero.")
        try:
            num = Decimal(str(valor))
        except InvalidOperation:
            raise bad("debe ser un número entero.")
        if num != num.to_integral_value():
            raise bad("debe ser un número entero.")
        valor = int(num)
    elif spec.tipo == TipoParametro.DECIMAL:
        if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
            raise bad("debe ser un número.")
        try:
            num = Decimal(str(valor))
        except InvalidOperation:
            raise bad("debe ser un número.")
        valor = float(num)
    elif spec.tipo == TipoParametro.BOOLEANO:
        if not isinstance(valor, bool):
            raise bad("debe ser verdadero o falso.")
    elif spec.tipo == TipoParametro.TEXTO:
        if not isinstance(valor, str):
            raise bad("debe ser un texto.")
        valor = valor.strip()
        if spec.email and valor and not _EMAIL_RE.match(valor):
            raise bad("debe ser un correo electrónico válido (o quedar vacío).")
    if spec.tipo in (TipoParametro.ENTERO, TipoParametro.DECIMAL):
        if spec.minimo is not None and valor < spec.minimo:
            raise bad(f"no puede ser menor que {spec.minimo:g}.")
        if spec.maximo is not None and valor > spec.maximo:
            raise bad(f"no puede ser mayor que {spec.maximo:g}.")
    if spec.tipo == TipoParametro.TEXTO and spec.max_len and len(valor) > spec.max_len:
        raise bad(f"no puede tener más de {spec.max_len} caracteres.")
    return valor


def list_params(db: Session) -> list[dict[str, Any]]:
    rows = {r.clave: r for r in db.scalars(select(ParametroSistema))}
    out = []
    for clave, spec in sorted(specs().items()):
        row = rows.get(clave)
        out.append({
            "clave": clave, "valor": row.valor if row is not None and row.valor is not None else spec.default,
            "valor_por_defecto": spec.default, "tipo": spec.tipo.value, "descripcion": spec.descripcion,
            "minimo": spec.minimo, "maximo": spec.maximo,
            "modificado": bool(row is not None and row.valor is not None and row.valor != spec.default),
            "updated_at": row.updated_at if row is not None else None,
        })
    return out


def update_param(db: Session, actor: Usuario, clave: str, valor: Any, *, request=None) -> dict[str, Any]:
    """Valida y guarda; deja constancia (anterior -> nuevo) en la auditoría. Sin commit."""
    spec = get_spec(clave)
    valor = validate_value(spec, valor)
    anterior = get_value(db, clave)
    if clave == aq10_config.PARAM_PUNTO_CORTE:
        aq10_config.set_punto_corte(db, actor, valor, request=request)
    else:
        params.set_param(db, clave, valor, descripcion=spec.descripcion)
        audit.log(db, actor, "PARAMETRO_MODIFICADO", "parametro_sistema", None,
                  {"clave": clave, "anterior": anterior, "nuevo": valor}, request=request)
    return {"clave": clave, "valor": valor, "anterior": anterior}
