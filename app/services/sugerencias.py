"""Sugerencias DUA (RF-15/16, HU-12): generar, listar, decidir (aceptar/modificar/rechazar) y texto accesible.

El slice C1 consume `get_accepted(db, estudiante_id)` para construir el borrador del F6.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.base import utcnow
from app.models.dua import EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import Escenario, EstadoBarrera, EstadoSugerencia, PrincipioDua, TipoBarrera
from app.models.mapa import BarreraIdentificada
from app.models.usuarios import Estudiante, Usuario
from app.services import ai_gateway, cbr


def get_accepted(db: Session, estudiante_id: int, *, plan_id: int | None = None) -> list[SugerenciaDua]:
    """Sugerencias ACEPTADAS o MODIFICADAS del estudiante, listas para el borrador F6 (más antiguas primero).

    El texto vigente de cada una es `texto_modificado` si existe (MODIFICADA) o la descripción del catálogo
    (`EstrategiaDuaCatalogo.descripcion_pedagogica`, accesible vía `estrategia_catalogo_id`).
    """
    stmt = select(SugerenciaDua).where(
        SugerenciaDua.estudiante_id == estudiante_id,
        SugerenciaDua.estado.in_([EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA]),
    )
    if plan_id is not None:
        stmt = stmt.where((SugerenciaDua.plan_id == plan_id) | (SugerenciaDua.plan_id.is_(None)))
    return list(db.scalars(stmt.order_by(SugerenciaDua.id)).all())


def get_suggestion(db: Session, sugerencia_id: int) -> SugerenciaDua:
    s = db.get(SugerenciaDua, sugerencia_id)
    if s is None:
        raise NotFound("No encontramos la sugerencia indicada.", "SUGERENCIA_NO_ENCONTRADA")
    return s


def generate(db: Session, est: Estudiante, *, barrera_ids: list[int] | None = None, max_por_barrera: int = 3) -> dict[str, Any]:
    stmt = select(BarreraIdentificada).where(BarreraIdentificada.estudiante_id == est.id,
                                             BarreraIdentificada.estado != EstadoBarrera.SUPERADA)
    if barrera_ids:
        stmt = stmt.where(BarreraIdentificada.id.in_(barrera_ids))
    barreras = list(db.scalars(stmt.order_by(BarreraIdentificada.id)).all())
    if barrera_ids and len(barreras) != len(set(barrera_ids)):
        raise Unprocessable("Algunas barreras no existen, ya fueron superadas o no son de este estudiante.", "BARRERAS_INVALIDAS")
    if not barreras:
        raise Conflict("Primero registre las barreras (F4): las sugerencias DUA se generan a partir de ellas.", "SIN_BARRERAS")
    previas = list(db.scalars(select(SugerenciaDua).where(SugerenciaDua.estudiante_id == est.id)).all())
    existentes: dict[tuple[int | None, int], SugerenciaDua] = {(s.barrera_id, s.estrategia_catalogo_id): s for s in previas}
    excluir: dict[int, set[int]] = {}
    for s in previas:
        if s.estado == EstadoSugerencia.RECHAZADA and s.barrera_id:
            excluir.setdefault(s.barrera_id, set()).add(s.estrategia_catalogo_id)  # lo rechazado no reaparece
    recs, sin = cbr.recommend(db, est.id, barreras, max_por_barrera=max_por_barrera, excluir_por_barrera=excluir)
    creadas: list[SugerenciaDua] = []
    actualizadas: list[SugerenciaDua] = []
    for r in recs:
        prev = existentes.get((r.barrera_id, r.estrategia.id))
        if prev is not None:
            if prev.estado == EstadoSugerencia.PROPUESTA:
                prev.puntaje_similitud, prev.justificacion, prev.origen = r.puntaje, r.justificacion, r.origen
                actualizadas.append(prev)
            continue
        s = SugerenciaDua(
            estudiante_id=est.id, barrera_id=r.barrera_id, estrategia_catalogo_id=r.estrategia.id,
            tipo_barrera=TipoBarrera(r.tipo_barrera), escenario=Escenario(r.escenario) if r.escenario else None,
            principio_dua=PrincipioDua(r.principio), origen=r.origen, puntaje_similitud=r.puntaje,
            justificacion=r.justificacion, estado=EstadoSugerencia.PROPUESTA,
        )
        db.add(s)
        creadas.append(s)
    db.flush()
    return {"creadas": creadas, "actualizadas": actualizadas, "barreras_sin_cobertura": sin,
            "barreras_evaluadas": [b.id for b in barreras]}


def serialize(db: Session, s: SugerenciaDua, *, cat: EstrategiaDuaCatalogo | None = None) -> dict[str, Any]:
    cat = cat or db.get(EstrategiaDuaCatalogo, s.estrategia_catalogo_id)
    return {
        "id": s.id, "estudiante_id": s.estudiante_id, "barrera_id": s.barrera_id, "plan_id": s.plan_id,
        "tipo_barrera": str(s.tipo_barrera) if s.tipo_barrera else None, "escenario": str(s.escenario) if s.escenario else None,
        "principio_dua": str(s.principio_dua), "origen": str(s.origen), "puntaje": s.puntaje_similitud,
        "justificacion": s.justificacion, "estado": str(s.estado), "motivo_decision": s.motivo_decision,
        "texto_modificado": s.texto_modificado, "texto_accesible": s.texto_accesible,
        "decidido_por_id": s.decidido_por_id, "decidido_at": s.decidido_at.isoformat() if s.decidido_at else None,
        "estrategia": {
            "id": cat.id, "codigo": cat.codigo, "nombre": cat.nombre, "descripcion_pedagogica": cat.descripcion_pedagogica,
            "principio": str(cat.principio), "pauta": cat.pauta, "pauta_nombre": cat.pauta_nombre,
            "punto_verificacion": cat.punto_verificacion, "escenarios": cat.escenarios, "tipos_barrera": cat.tipos_barrera,
        } if cat else None,
        "created_at": s.created_at.isoformat(),
    }


def list_for_student(db: Session, estudiante_id: int, *, estado: EstadoSugerencia | None = None, principio: PrincipioDua | None = None,
                     pauta: int | None = None, escenario: Escenario | None = None, tipo_barrera: TipoBarrera | None = None,
                     barrera_id: int | None = None, solo_vigentes: bool = False) -> list[SugerenciaDua]:
    stmt = select(SugerenciaDua).where(SugerenciaDua.estudiante_id == estudiante_id)
    if solo_vigentes:
        stmt = stmt.where(SugerenciaDua.estado.in_([EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA]))
    if estado:
        stmt = stmt.where(SugerenciaDua.estado == estado)
    if principio:
        stmt = stmt.where(SugerenciaDua.principio_dua == principio)
    if escenario:
        stmt = stmt.where(SugerenciaDua.escenario == escenario)
    if tipo_barrera:
        stmt = stmt.where(SugerenciaDua.tipo_barrera == tipo_barrera)
    if barrera_id:
        stmt = stmt.where(SugerenciaDua.barrera_id == barrera_id)
    rows = list(db.scalars(stmt.order_by(SugerenciaDua.puntaje_similitud.desc(), SugerenciaDua.id)).all())
    if pauta is not None:
        pautas = {c.id: c.pauta for c in db.scalars(select(EstrategiaDuaCatalogo))}
        rows = [r for r in rows if pautas.get(r.estrategia_catalogo_id) == pauta]
    return rows


def _decide(s: SugerenciaDua, actor: Usuario, estado: EstadoSugerencia, motivo: str | None) -> None:
    s.estado = estado
    s.decidido_por_id = actor.id
    s.decidido_at = utcnow()
    s.motivo_decision = (motivo or "").strip() or None


def accept(db: Session, s: SugerenciaDua, actor: Usuario, nota: str | None = None) -> SugerenciaDua:
    if s.estado != EstadoSugerencia.PROPUESTA:
        raise Conflict("Esta sugerencia ya fue decidida.", "SUGERENCIA_YA_DECIDIDA")
    _decide(s, actor, EstadoSugerencia.ACEPTADA, nota)
    db.flush()
    return s


def modify(db: Session, s: SugerenciaDua, actor: Usuario, texto: str, motivo: str | None) -> SugerenciaDua:
    if s.estado not in (EstadoSugerencia.PROPUESTA, EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA):
        raise Conflict("Una sugerencia rechazada no se puede modificar.", "SUGERENCIA_YA_DECIDIDA")
    if len((texto or "").strip()) < 5:
        raise Unprocessable("Escriba la versión modificada de la estrategia.", "TEXTO_REQUERIDO")
    _decide(s, actor, EstadoSugerencia.MODIFICADA, motivo)
    s.texto_modificado = texto.strip()
    db.flush()
    return s


def reject(db: Session, s: SugerenciaDua, actor: Usuario, motivo: str) -> SugerenciaDua:
    if s.estado != EstadoSugerencia.PROPUESTA:
        raise Conflict("Esta sugerencia ya fue decidida.", "SUGERENCIA_YA_DECIDIDA")
    if len((motivo or "").strip()) < 5:
        raise Unprocessable("Para rechazar una sugerencia explique el motivo (mínimo 5 caracteres): ayuda a mejorar el motor.",
                            "MOTIVO_REQUERIDO")
    _decide(s, actor, EstadoSugerencia.RECHAZADA, motivo)
    cbr.register_rejection(db, s)
    db.flush()
    return s


def accessible_text(db: Session, s: SugerenciaDua) -> ai_gateway.AIResult:
    if s.estado == EstadoSugerencia.RECHAZADA:
        raise Conflict("No se genera texto para una sugerencia rechazada.", "SUGERENCIA_RECHAZADA")
    if s.tipo_barrera is None or s.escenario is None:
        raise Unprocessable("La barrera de esta sugerencia no tiene escenario: complételo en el F4 para generar el texto.",
                            "SUGERENCIA_SIN_ESCENARIO")
    res = ai_gateway.generate_accessible_text(ai_gateway.AIPromptInput(s.tipo_barrera, s.escenario, s.principio_dua))
    s.texto_accesible = res.texto
    db.flush()
    return res
