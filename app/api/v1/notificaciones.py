"""Notificaciones in-app (M10, RF-30/39): solo las propias. Contrato con el frontend: `{items, total, no_leidas}`.

# OWNER: slice A. No exige F0 (el estudiante debe poder ver el aviso «Falta firmar su consentimiento»).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_roles
from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.enums import EstadoEmail, Rol
from app.models.sistema import EmailOutbox, Notificacion
from app.models.usuarios import Usuario

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


def _item(n: Notificacion) -> dict:
    return {"id": n.id, "tipo": n.tipo, "titulo": n.titulo, "mensaje": n.mensaje, "leida": bool(n.leida),
            "created_at": n.created_at, "enlace": n.enlace}


def _no_leidas(db: Session, uid: int) -> int:
    return int(db.scalar(select(func.count()).select_from(Notificacion).where(
        Notificacion.usuario_id == uid, Notificacion.leida.is_(False))) or 0)


@router.get("")
def listar(solo_no_leidas: bool = Query(False), params: PageParams = Depends(), db: Session = Depends(get_db),
           user: Usuario = Depends(get_current_user)):
    stmt = select(Notificacion).where(Notificacion.usuario_id == user.id).order_by(Notificacion.created_at.desc(), Notificacion.id.desc())
    if solo_no_leidas:
        stmt = stmt.where(Notificacion.leida.is_(False))
    page = paginate(db, stmt, params, _item)
    return {**page, "no_leidas": _no_leidas(db, user.id)}


@router.post("/leer-todas")
def leer_todas(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ahora = utcnow()
    res = db.execute(update(Notificacion).where(Notificacion.usuario_id == user.id, Notificacion.leida.is_(False))
                     .values(leida=True, leida_at=ahora))
    db.commit()
    return {"marcadas": res.rowcount or 0, "no_leidas": 0}


@router.get("/outbox")
def outbox(estado: EstadoEmail | None = None, params: PageParams = Depends(), db: Session = Depends(get_db),
           _: Usuario = Depends(require_roles(Rol.ADMIN))):
    """Cola de correo (solo Admin). No incluye el cuerpo de los mensajes."""
    stmt = select(EmailOutbox).order_by(EmailOutbox.id.desc())
    if estado:
        stmt = stmt.where(EmailOutbox.estado == estado)
    return paginate(db, stmt, params, lambda r: {
        "id": r.id, "destinatario_email": r.destinatario_email, "asunto": r.asunto, "evento": r.evento,
        "estado": str(r.estado), "intentos": r.intentos, "ultimo_error": r.ultimo_error, "created_at": r.created_at,
        "enviado_at": r.enviado_at,
    })


@router.post("/{notificacion_id}/leer")
def leer(notificacion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    n = db.get(Notificacion, notificacion_id)
    if n is None or n.usuario_id != user.id:
        raise NotFound("No encontramos esa notificación.", "NOTIFICACION_NO_ENCONTRADA")
    if not n.leida:
        n.leida, n.leida_at = True, utcnow()
        db.commit()
    return {"id": n.id, "leida": True, "no_leidas": _no_leidas(db, user.id)}
