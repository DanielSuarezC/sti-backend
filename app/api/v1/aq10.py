"""AQ-10: formulario, aplicación (asistida / autoaplicación) y consulta. Ver docs/api/slice_b.md.

# OWNER: slice B
El resultado SOLO lo ven Bienestar y el propio estudiante (RF-11). Docente, Coordinador, Familiar y Admin reciben 403.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.models.consentimiento import RespuestaAQ10
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.aq10 import Aq10In
from app.services import aq10 as svc

router = APIRouter(tags=["aq10"])


@router.get("/aq10/formulario", summary="Ítems, opciones y protocolo de bienvenida del AQ-10")
def formulario(db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    cfg = svc.get_config(db)
    db.commit()
    return {
        "cuestionario_id": cfg["id"], "version": cfg["version"], "nombre": cfg["nombre"], "idioma": cfg["idioma"],
        "fuente": cfg["fuente"], "items": [{"numero": i["numero"], "texto": i["texto"]} for i in cfg["items"]],
        "opciones": [{"valor": o["valor"], "etiqueta": o["etiqueta"]} for o in cfg["opciones"]],
        "instrucciones": cfg.get("instrucciones"), "protocolo_bienvenida": svc.PROTOCOLO_BIENVENIDA,
        "mensaje_tamizaje": svc.MENSAJE_TAMIZAJE,
        "revision_linguistica_pendiente": cfg.get("revision_linguistica_pendiente", True),
    }


@router.post("/estudiantes/{estudiante_id}/aq10", status_code=201, summary="Aplicar el AQ-10 (asistida o autoaplicación)")
def aplicar(estudiante_id: int, body: Aq10In, request: Request, db: Session = Depends(get_db),
            user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    accion = Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR
    est = assert_can(db, user, estudiante_id, Recurso.AQ10, accion)
    out = svc.apply(db, est, user, body.respuestas, request)
    db.commit()
    resp = svc.serialize(out["row"])
    resp.update({k: v for k, v in out.items() if k not in ("row", "cfg", "puntaje", "punto_corte", "supera_umbral")})
    return resp


@router.get("/estudiantes/{estudiante_id}/aq10", summary="Aplicaciones del AQ-10 de un estudiante (auditado)")
def listar(estudiante_id: int, request: Request, db: Session = Depends(get_db),
           user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    assert_can(db, user, estudiante_id, Recurso.AQ10, Accion.LEER)
    rows = db.scalars(select(RespuestaAQ10).where(RespuestaAQ10.estudiante_id == estudiante_id)
                      .order_by(RespuestaAQ10.aplicado_at.desc(), RespuestaAQ10.id.desc())).all()
    audit.log(db, user, audit.Accion.ACCESO_AQ10, "respuesta_aq10", None, {"registros": len(rows)}, request=request,
              estudiante_id=estudiante_id)
    db.commit()
    return {"items": [svc.serialize(r) for r in rows], "total": len(rows), "mensaje_tamizaje": svc.MENSAJE_TAMIZAJE}
