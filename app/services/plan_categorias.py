"""Registro categoría -> subentidad RESPUESTA_* de los ajustes razonables (RF-22, 6 categorías).

Cada ajuste tiene un `tipo_ajuste` (comunicación, pedagogía, evaluación, ambiente, interacción, tecnología) y una fila de
detalle en la tabla de respuesta de su categoría. El API recibe/entrega ``detalle = {tipo, descripcion, soporte_tecnico_requerido?}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Unprocessable
from app.models.enums import (
    TipoAjuste,
    TipoAmbientalAjuste,
    TipoComunicacionAjuste,
    TipoEvaluativoAjuste,
    TipoInteraccionAjuste,
    TipoPedagogicoAjuste,
    TipoTecnologicoAjuste,
)
from app.models.plan import (
    AjusteRazonable,
    RespuestaAmbiente,
    RespuestaComunicacion,
    RespuestaEvaluacion,
    RespuestaInteraccion,
    RespuestaPedagogia,
    RespuestaTecnologia,
)


@dataclass(frozen=True)
class Categoria:
    model: type
    enum: type[StrEnum]
    col_tipo: str
    col_desc: str
    etiqueta: str


CATEGORIAS: dict[TipoAjuste, Categoria] = {
    TipoAjuste.COMUNICACION: Categoria(
        RespuestaComunicacion, TipoComunicacionAjuste, "tipo_comunicacion_ajuste", "especificacion", "Comunicación"),
    TipoAjuste.PEDAGOGIA: Categoria(
        RespuestaPedagogia, TipoPedagogicoAjuste, "tipo_pedagogico_ajuste", "descripcion", "Pedagogía"),
    TipoAjuste.EVALUACION: Categoria(
        RespuestaEvaluacion, TipoEvaluativoAjuste, "tipo_evaluativo_ajuste", "descripcion_especifica", "Evaluación"),
    TipoAjuste.AMBIENTE: Categoria(
        RespuestaAmbiente, TipoAmbientalAjuste, "tipo_ambiental_ajuste", "descripcion", "Ambiente"),
    TipoAjuste.INTERACCION: Categoria(
        RespuestaInteraccion, TipoInteraccionAjuste, "tipo_interaccion_ajuste", "descripcion", "Interacción"),
    TipoAjuste.TECNOLOGIA: Categoria(
        RespuestaTecnologia, TipoTecnologicoAjuste, "tipo_tecnologico_ajuste", "descripcion_tecnologia", "Tecnología"),
}

ETIQUETAS = {t.value: c.etiqueta for t, c in CATEGORIAS.items()}


def categoria(tipo: TipoAjuste | str) -> Categoria:
    return CATEGORIAS[TipoAjuste(str(tipo))]


def tipos_validos(tipo: TipoAjuste | str) -> list[str]:
    return [m.value for m in categoria(tipo).enum]


def validar_detalle(tipo_ajuste: TipoAjuste | str, detalle: dict | None) -> dict | None:
    """Normaliza y valida ``detalle`` contra la categoría. Lanza 422 `DETALLE_AJUSTE_INVALIDO`."""
    if not detalle:
        return None
    cat = categoria(tipo_ajuste)
    tipo = detalle.get("tipo")
    try:
        tipo_enum = cat.enum(str(tipo).upper())
    except ValueError:
        raise Unprocessable(
            f"El tipo de detalle «{tipo}» no corresponde a la categoría {TipoAjuste(str(tipo_ajuste)).value}. "
            f"Elija uno de: {', '.join(tipos_validos(tipo_ajuste))}.",
            "DETALLE_AJUSTE_INVALIDO",
            extra={"tipos_validos": tipos_validos(tipo_ajuste)},
        )
    out = {"tipo": tipo_enum.value, "descripcion": (detalle.get("descripcion") or None)}
    if TipoAjuste(str(tipo_ajuste)) == TipoAjuste.TECNOLOGIA:
        out["soporte_tecnico_requerido"] = bool(detalle.get("soporte_tecnico_requerido", False))
    return out


def leer_detalle(db: Session, ajuste: AjusteRazonable) -> dict | None:
    cat = categoria(ajuste.tipo_ajuste)
    db.flush()
    row = db.scalar(select(cat.model).where(cat.model.ajuste_id == ajuste.id).order_by(cat.model.id))
    if row is None:
        return None
    out = {"tipo": str(getattr(row, cat.col_tipo)), "descripcion": getattr(row, cat.col_desc)}
    if TipoAjuste(str(ajuste.tipo_ajuste)) == TipoAjuste.TECNOLOGIA:
        out["soporte_tecnico_requerido"] = bool(row.soporte_tecnico_requerido)
    return out


def borrar_detalles(db: Session, ajuste: AjusteRazonable, actor_id: int | None, motivo: str) -> None:
    """Soft delete de todas las filas de detalle del ajuste (todas las categorías)."""
    db.flush()
    for cat in CATEGORIAS.values():
        for row in db.scalars(select(cat.model).where(cat.model.ajuste_id == ajuste.id)):
            row.soft_delete(actor_id, motivo)


def escribir_detalle(db: Session, ajuste: AjusteRazonable, detalle: dict | None, actor_id: int | None = None) -> None:
    """Reemplaza el detalle del ajuste (soft delete de lo anterior + fila nueva). ``detalle`` ya validado."""
    borrar_detalles(db, ajuste, actor_id, "Detalle reemplazado")
    if not detalle:
        return
    cat = categoria(ajuste.tipo_ajuste)
    kwargs = {"ajuste_id": ajuste.id, cat.col_tipo: cat.enum(detalle["tipo"]), cat.col_desc: detalle.get("descripcion")}
    if TipoAjuste(str(ajuste.tipo_ajuste)) == TipoAjuste.TECNOLOGIA:
        kwargs["soporte_tecnico_requerido"] = bool(detalle.get("soporte_tecnico_requerido", False))
    db.add(cat.model(**kwargs))
    db.flush()
