"""Configuración versionada del AQ-10 (M1, RF-08, HU-02).

El slice B aplica el cuestionario leyendo `get_active_config(db)`. Cada cambio de ítems/opciones crea una NUEVA
versión de `CUESTIONARIO_AQ10` (la anterior queda inactiva): las respuestas históricas conservan su
`cuestionario_id` y su `punto_corte_aplicado`, por lo que nunca se alteran.

Convenciones de datos (idénticas a la semilla `app/data/aq10.py`):
  items    = [{"numero": 1..10, "texto": str, "puntua_si": "ACUERDO" | "DESACUERDO"}]
  opciones = [{"valor": 1..4, "etiqueta": str, "direccion": "ACUERDO" | "DESACUERDO"}]  (Likert de 4)
Una respuesta puntúa 1 cuando la `direccion` de la opción elegida coincide con `puntua_si` del ítem.
Las instrucciones viven en el parámetro `aq10_instrucciones`; el punto de corte en `aq10_punto_corte` (1-10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import NotFound, Unprocessable
from app.models.consentimiento import CuestionarioAQ10
from app.models.usuarios import Usuario
from app.services import params

INSTRUCCIONES_POR_DEFECTO = (
    "Lea cada frase y elija la opción que mejor describa cómo es usted en general. No hay respuestas buenas ni "
    "malas. Este cuestionario es una herramienta de tamizaje: no es un diagnóstico y no etiqueta a nadie. "
    "Puede tomarse el tiempo que necesite."
)
PARAM_INSTRUCCIONES = "aq10_instrucciones"
PARAM_PUNTO_CORTE = "aq10_punto_corte"
DIRECCIONES = ("ACUERDO", "DESACUERDO")


@dataclass
class Aq10Config:
    id: int
    version: str
    nombre: str
    idioma: str
    fuente: str | None
    items: list[dict[str, Any]]
    opciones: list[dict[str, Any]]
    punto_corte: int
    instrucciones: str
    revision_linguistica_pendiente: bool
    activo: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "version": self.version, "nombre": self.nombre, "idioma": self.idioma, "fuente": self.fuente,
            "items": self.items, "opciones": self.opciones, "punto_corte": self.punto_corte,
            "instrucciones": self.instrucciones,
            "revision_linguistica_pendiente": self.revision_linguistica_pendiente, "activo": self.activo,
        }


def _to_config(db: Session, c: CuestionarioAQ10) -> Aq10Config:
    corte = params.get_param(db, PARAM_PUNTO_CORTE, c.punto_corte)
    return Aq10Config(
        id=c.id, version=c.version, nombre=c.nombre, idioma=c.idioma, fuente=c.fuente,
        items=list(c.items or []), opciones=list(c.opciones or []),
        punto_corte=int(corte if corte is not None else c.punto_corte),
        instrucciones=params.get_param(db, PARAM_INSTRUCCIONES) or INSTRUCCIONES_POR_DEFECTO,
        revision_linguistica_pendiente=bool(c.revision_linguistica_pendiente), activo=bool(c.activo),
    )


def get_active_row(db: Session) -> CuestionarioAQ10 | None:
    return db.scalar(
        select(CuestionarioAQ10).where(CuestionarioAQ10.activo.is_(True)).order_by(CuestionarioAQ10.id.desc())
    )


def get_active_config(db: Session) -> Aq10Config:
    """Configuración vigente del AQ-10 (para el slice B). 404 `AQ10_NO_CONFIGURADO` si el Admin aún no la cargó."""
    row = get_active_row(db)
    if row is None:
        raise NotFound("El AQ-10 aún no está configurado. Pida al administrador que lo cargue.", "AQ10_NO_CONFIGURADO")
    return _to_config(db, row)


def list_versions(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(CuestionarioAQ10).order_by(CuestionarioAQ10.id.desc())).all()
    return [{"id": r.id, "version": r.version, "activo": bool(r.activo), "created_at": r.created_at} for r in rows]


def _next_version(db: Session) -> str:
    mayor = 0
    for v in db.scalars(select(CuestionarioAQ10.version).execution_options(include_deleted=True)):
        try:
            mayor = max(mayor, int(str(v).split(".")[0]))
        except ValueError:
            continue
    return f"{mayor + 1}.0"


def validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(items) != 10:
        raise Unprocessable(f"El AQ-10 debe tener exactamente 10 ítems (recibimos {len(items)}).", "AQ10_ITEMS_INVALIDOS")
    numeros = sorted(int(i["numero"]) for i in items)
    if numeros != list(range(1, 11)):
        raise Unprocessable("Los ítems deben estar numerados del 1 al 10, sin repetir.", "AQ10_ITEMS_INVALIDOS")
    out = []
    for it in sorted(items, key=lambda x: int(x["numero"])):
        texto = str(it.get("texto", "")).strip()
        if not texto:
            raise Unprocessable(f"El ítem {it['numero']} no tiene texto.", "AQ10_ITEMS_INVALIDOS")
        if it.get("puntua_si") not in DIRECCIONES:
            raise Unprocessable(f"El ítem {it['numero']} debe indicar si puntúa con ACUERDO o DESACUERDO.",
                                "AQ10_ITEMS_INVALIDOS")
        out.append({"numero": int(it["numero"]), "texto": texto, "puntua_si": it["puntua_si"]})
    return out


def validate_opciones(opciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(opciones) != 4:
        raise Unprocessable(f"La escala debe tener exactamente 4 opciones (recibimos {len(opciones)}).",
                            "AQ10_OPCIONES_INVALIDAS")
    if sorted(int(o["valor"]) for o in opciones) != [1, 2, 3, 4]:
        raise Unprocessable("Las opciones deben tener los valores 1, 2, 3 y 4, sin repetir.", "AQ10_OPCIONES_INVALIDAS")
    out = []
    for o in sorted(opciones, key=lambda x: int(x["valor"])):
        etiqueta = str(o.get("etiqueta", "")).strip()
        if not etiqueta:
            raise Unprocessable(f"La opción {o['valor']} no tiene etiqueta.", "AQ10_OPCIONES_INVALIDAS")
        if o.get("direccion") not in DIRECCIONES:
            raise Unprocessable(f"La opción {o['valor']} debe ser de ACUERDO o de DESACUERDO.", "AQ10_OPCIONES_INVALIDAS")
        out.append({"valor": int(o["valor"]), "etiqueta": etiqueta, "direccion": o["direccion"]})
    if sum(1 for o in out if o["direccion"] == "ACUERDO") != 2:
        raise Unprocessable("Una escala Likert de 4 puntos tiene 2 opciones de acuerdo y 2 de desacuerdo.",
                            "AQ10_OPCIONES_INVALIDAS")
    return out


def validate_punto_corte(valor: int) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool) or not 1 <= valor <= 10:
        raise Unprocessable("El punto de corte debe ser un número entero entre 1 y 10.", "AQ10_PUNTO_CORTE_INVALIDO")
    return valor


def save_new_version(
    db: Session, actor: Usuario, *, items: list[dict], opciones: list[dict], instrucciones: str | None,
    nombre: str | None, idioma: str | None, fuente: str | None, revision_linguistica_pendiente: bool | None,
    punto_corte: int | None, request=None,
) -> CuestionarioAQ10:
    """Crea una versión nueva activa y desactiva la anterior. Sin commit."""
    items = validate_items(items)
    opciones = validate_opciones(opciones)
    previa = get_active_row(db)
    if punto_corte is not None:
        corte = validate_punto_corte(punto_corte)
    else:
        corte = int(params.get_param(db, PARAM_PUNTO_CORTE, previa.punto_corte if previa else 6))
    if previa is not None:
        previa.activo = False
    nueva = CuestionarioAQ10(
        nombre=nombre or (previa.nombre if previa else "AQ-10 Adultos"),
        version=_next_version(db),
        idioma=idioma or (previa.idioma if previa else "es-CO"),
        fuente=fuente if fuente is not None else (previa.fuente if previa else None),
        items=items, opciones=opciones, punto_corte=corte,
        revision_linguistica_pendiente=(
            revision_linguistica_pendiente if revision_linguistica_pendiente is not None
            else (previa.revision_linguistica_pendiente if previa else True)
        ),
        activo=True,
    )
    db.add(nueva)
    db.flush()
    params.set_param(db, PARAM_PUNTO_CORTE, corte)
    if instrucciones is not None:
        params.set_param(db, PARAM_INSTRUCCIONES, instrucciones.strip(),
                         descripcion="Texto de instrucciones que ve la persona al responder el AQ-10.")
    audit.log(db, actor, "AQ10_CONFIG_ACTUALIZADA", "cuestionario_aq10", nueva.id,
              {"version": nueva.version, "version_anterior": previa.version if previa else None, "punto_corte": corte,
               "revision_linguistica_pendiente": nueva.revision_linguistica_pendiente}, request=request)
    return nueva


def set_punto_corte(db: Session, actor: Usuario, valor: int, *, request=None) -> int:
    """Cambia `aq10_punto_corte` (y el de la versión activa). Las respuestas históricas conservan su corte. Sin commit."""
    valor = validate_punto_corte(valor)
    anterior = params.get_param(db, PARAM_PUNTO_CORTE)
    params.set_param(db, PARAM_PUNTO_CORTE, valor)
    row = get_active_row(db)
    if row is not None:
        row.punto_corte = valor
    audit.log(db, actor, "PARAMETRO_MODIFICADO", "parametro_sistema", None,
              {"clave": PARAM_PUNTO_CORTE, "anterior": anterior, "nuevo": valor}, request=request)
    return valor
