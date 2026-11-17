"""F1 (caracterización) y F2 (perfil de fortalezas) por sección. Ver docs/api/slice_b.md.

# OWNER: slice B
Docente NUNCA (403). Cada lectura de contenido se audita (RF-38).
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.core.errors import Forbidden
from app.models.enums import Rol
from app.models.usuarios import Usuario
from app.schemas.caracterizacion import F1_SECCIONES_IN, F2_SECCIONES_IN, ComentarioIn
from app.services import caracterizacion as svc
from app.services.b_common import AccionB

router = APIRouter(tags=["caracterizacion"])

_LEER = require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE, Rol.FAMILIAR)
_ESCRIBIR = require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE)


def _check_read(db, user, est_id):
    return assert_can(db, user, est_id, Recurso.CARACTERIZACION, Accion.LEER)


def _check_write(db, user, est_id, *, seccion_estudiante: bool):
    """Bienestar: ESCRIBIR. Estudiante: APORTAR, solo en las secciones que le corresponden (su voz)."""
    if str(user.rol) == Rol.BIENESTAR:
        return assert_can(db, user, est_id, Recurso.CARACTERIZACION, Accion.ESCRIBIR)
    est = assert_can(db, user, est_id, Recurso.CARACTERIZACION, Accion.APORTAR)
    if not seccion_estudiante:
        raise Forbidden("Esta sección la completa el equipo de Bienestar. Usted puede escribir en «En mis palabras» "
                        "y dejar comentarios.", "SECCION_SOLO_BIENESTAR")
    return est


# ============================================================================ F1
@router.get("/estudiantes/{estudiante_id}/caracterizacion", summary="F1 completo (auditado)")
def f1_ver(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    car = svc.current_f1(db, estudiante_id)
    audit.log(db, user, AccionB.ACCESO_F1, "caracterizacion", car.id if car else None, {"vista": "completa"},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f1_view(db, estudiante_id, car)


@router.get("/estudiantes/{estudiante_id}/caracterizacion/progreso", summary="Progreso de F1")
def f1_progreso(estudiante_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    return svc.f1_progress(db, svc.current_f1(db, estudiante_id))


@router.get("/estudiantes/{estudiante_id}/caracterizacion/vista-previa", summary="Perfil generado de F1 (auditado)")
def f1_vista_previa(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    car = svc.current_f1(db, estudiante_id)
    audit.log(db, user, AccionB.ACCESO_F1, "caracterizacion", car.id if car else None, {"vista": "vista_previa"},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f1_preview(db, estudiante_id, car)


def _make_f1_patch(seccion: str, schema):
    def endpoint(estudiante_id: int, body: schema, request: Request, db: Session = Depends(get_db),  # type: ignore[valid-type]
                 user: Usuario = Depends(_ESCRIBIR)):
        est = _check_write(db, user, estudiante_id, seccion_estudiante=seccion in svc.F1_ESTUDIANTE)
        car = svc.save_f1_section(db, est, user, seccion, body)
        audit.log(db, user, AccionB.ESCRITURA_F1, "caracterizacion", car.id, {"seccion": seccion, "version": car.version},
                  request=request, estudiante_id=estudiante_id)
        db.commit()
        return {"seccion": seccion, "guardado": True, **svc.f1_progress(db, car)}

    endpoint.__name__ = f"f1_patch_{seccion}"
    router.add_api_route(f"/estudiantes/{{estudiante_id}}/caracterizacion/{seccion}", endpoint, methods=["PATCH"],
                         summary=f"Guardar la sección «{seccion}» de F1 (idempotente)")


for _s, _sch in list(F1_SECCIONES_IN.items()):
    _make_f1_patch(_s, _sch)


@router.post("/estudiantes/{estudiante_id}/caracterizacion/confirmar", summary="Confirmar F1 (Bienestar)")
def f1_confirmar(estudiante_id: int, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    assert_can(db, user, estudiante_id, Recurso.CARACTERIZACION, Accion.ESCRIBIR)
    car = svc.confirm_f1(db, svc.current_f1(db, estudiante_id), user)
    audit.log(db, user, AccionB.FORMATO_CONFIRMADO, "caracterizacion", car.id, {"formato": "F1", "version": car.version},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f1_progress(db, car)


# ============================================================================ F2
@router.get("/estudiantes/{estudiante_id}/fortalezas", summary="F2 completo (auditado)")
def f2_ver(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    p = svc.current_f2(db, estudiante_id)
    audit.log(db, user, AccionB.ACCESO_F2, "perfil_fortalezas", p.id if p else None, {"vista": "completa"},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f2_view(db, estudiante_id, p)


@router.get("/estudiantes/{estudiante_id}/fortalezas/progreso", summary="Progreso de F2")
def f2_progreso(estudiante_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    return svc.f2_progress(db, svc.current_f2(db, estudiante_id))


@router.get("/estudiantes/{estudiante_id}/fortalezas/vista-previa", summary="Perfil generado de F2 (auditado)")
def f2_vista_previa(estudiante_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    _check_read(db, user, estudiante_id)
    p = svc.current_f2(db, estudiante_id)
    audit.log(db, user, AccionB.ACCESO_F2, "perfil_fortalezas", p.id if p else None, {"vista": "vista_previa"},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f2_preview(db, estudiante_id, p)


def _make_f2_patch(seccion: str, schema):
    def endpoint(estudiante_id: int, body: schema, request: Request, db: Session = Depends(get_db),  # type: ignore[valid-type]
                 user: Usuario = Depends(_ESCRIBIR)):
        est = _check_write(db, user, estudiante_id, seccion_estudiante=True)  # F2: el estudiante aporta en toda la sección
        p = svc.save_f2_section(db, est, user, seccion, body)
        audit.log(db, user, AccionB.ESCRITURA_F2, "perfil_fortalezas", p.id, {"seccion": seccion, "version": p.version},
                  request=request, estudiante_id=estudiante_id)
        db.commit()
        return {"seccion": seccion, "guardado": True, **svc.f2_progress(db, p)}

    endpoint.__name__ = f"f2_patch_{seccion}"
    router.add_api_route(f"/estudiantes/{{estudiante_id}}/fortalezas/{seccion}", endpoint, methods=["PATCH"],
                         summary=f"Guardar la sección «{seccion}» de F2 (idempotente)")


for _s, _sch in list(F2_SECCIONES_IN.items()):
    _make_f2_patch(_s, _sch)


@router.post("/estudiantes/{estudiante_id}/fortalezas/confirmar", summary="Confirmar F2 (Bienestar)")
def f2_confirmar(estudiante_id: int, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    assert_can(db, user, estudiante_id, Recurso.CARACTERIZACION, Accion.ESCRIBIR)
    p = svc.confirm_f2(db, svc.current_f2(db, estudiante_id), user)
    audit.log(db, user, AccionB.FORMATO_CONFIRMADO, "perfil_fortalezas", p.id, {"formato": "F2", "version": p.version},
              request=request, estudiante_id=estudiante_id)
    db.commit()
    return svc.f2_progress(db, p)


# ============================================================================ comentarios (voz del estudiante)
@router.post("/estudiantes/{estudiante_id}/comentarios-formato", status_code=201,
             summary="Comentario sobre una sección de F1/F2 (voz del estudiante; no crea versión)")
def comentar(estudiante_id: int, body: ComentarioIn, request: Request, db: Session = Depends(get_db),
             user: Usuario = Depends(_ESCRIBIR)):
    est = _check_write(db, user, estudiante_id, seccion_estudiante=True)
    c = svc.add_comment(db, est, user, body.formato, body.seccion, body.texto)
    audit.log(db, user, AccionB.ESCRITURA_F1 if body.formato == "F1" else AccionB.ESCRITURA_F2, "formato_comentario", c.id,
              {"seccion": body.seccion}, request=request, estudiante_id=estudiante_id)
    db.commit()
    return {"id": c.id, "formato": body.formato, "seccion": c.seccion, "texto": c.texto, "autor_rol": c.autor_rol,
            "created_at": c.created_at.isoformat()}
