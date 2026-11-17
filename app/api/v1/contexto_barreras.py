"""F3 (contexto), F4 (barreras) y F5 (facilitadores). Ver docs/api/slice_b.md.

# OWNER: slice B
Sin `from __future__ import annotations`: los endpoints de escenarios se generan con anotaciones dinámicas.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.core.errors import Forbidden, NotFound
from app.models.contexto import ContextoUniversitario
from app.models.enums import Escenario, EstadoBarrera, Rol, TipoBarrera, TipoFacilitador
from app.models.mapa import BarreraIdentificada, Facilitador
from app.models.usuarios import Usuario
from app.schemas import contexto_barreras as sch
from app.services import contexto_barreras as svc
from app.services.b_common import AccionB, soft_delete_obj

router = APIRouter(tags=["contexto-barreras"])

_LEER = require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE)
_BIENESTAR = require_roles_consent(Rol.BIENESTAR)


# ============================================================================ catálogos
@router.get("/mapa/catalogos", summary="Enums y campos por escenario / tipo de barrera / tipo de facilitador")
def catalogos(user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))):
    return {
        "escenarios": [{"valor": str(e), "nombre": sch.ESCENARIO_NOMBRES[e], "campos": sch.describe(sch.ESCENARIO_IN[e])} for e in Escenario],
        "facetas_contexto": {"docente": sch.describe(sch.DocenteCtxItem), "evaluacion": sch.describe(sch.EvaluacionCtxIn)},
        "tipos_barrera": [{"valor": str(t), "detalle": sch.describe(sch.BARRERA_DETALLE_IN[t]),
                           "requiere_respuesta_institucional": t == TipoBarrera.SOCIAL} for t in TipoBarrera],
        "tipos_facilitador": [{"valor": str(t), "detalle": sch.describe(sch.FACILITADOR_DETALLE_IN[t])} for t in TipoFacilitador],
        "estados_barrera": [str(e) for e in EstadoBarrera],
    }


# ============================================================================ F3
def _ctx_or_404(db: Session, est_id: int, semestre: str) -> ContextoUniversitario:
    svc.check_semestre(semestre)
    ctx = svc.get_context(db, est_id, semestre)
    if ctx is None:
        raise NotFound("Aún no existe el análisis de contexto (F3) de ese semestre.", "CONTEXTO_NO_ENCONTRADO")
    return ctx


def _write_ctx(db: Session, user: Usuario, est_id: int, *, aporte_coordinador: bool):
    """Bienestar escribe todo; el Coordinador APORTA solo en escenarios y facetas (docente/evaluación)."""
    if str(user.rol) == Rol.BIENESTAR:
        return assert_can(db, user, est_id, Recurso.CONTEXTO, Accion.ESCRIBIR)
    est = assert_can(db, user, est_id, Recurso.CONTEXTO, Accion.APORTAR)
    if not aporte_coordinador:
        raise Forbidden("Esta parte del contexto la completa Bienestar.", "SECCION_SOLO_BIENESTAR")
    return est


_ESCRIBIR_CTX = require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR)


@router.get("/estudiantes/{estudiante_id}/contextos", summary="Semestres con F3")
def contextos(estudiante_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.CONTEXTO, Accion.LEER)
    rows = db.scalars(select(ContextoUniversitario).where(ContextoUniversitario.estudiante_id == estudiante_id)
                      .order_by(ContextoUniversitario.semestre_academico.desc())).all()
    return {"items": [{"id": c.id, "semestre_academico": c.semestre_academico, "fecha_analisis": c.fecha_analisis.isoformat(),
                       "porcentaje": svc.context_progress(db, c)["porcentaje"]} for c in rows], "total": len(rows)}


@router.post("/estudiantes/{estudiante_id}/contexto", status_code=201, summary="Crear el F3 de un semestre (con precarga)")
def contexto_crear(estudiante_id: int, body: sch.ContextoCrearIn, request: Request, db: Session = Depends(get_db),
                   user: Usuario = Depends(_BIENESTAR)):
    est = assert_can(db, user, estudiante_id, Recurso.CONTEXTO, Accion.ESCRIBIR)
    ctx, pre = svc.create_context(db, est, user, body.semestre_academico, precargar=body.precargar)
    audit.log(db, user, AccionB.CONTEXTO_MODIFICADO, "contexto_universitario", ctx.id, {"creado": True}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.context_view(db, ctx, pre)


@router.get("/estudiantes/{estudiante_id}/contexto/{semestre}", summary="F3 de un semestre")
def contexto_ver(estudiante_id: int, semestre: str, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.CONTEXTO, Accion.LEER)
    return svc.context_view(db, _ctx_or_404(db, estudiante_id, semestre))


@router.get("/estudiantes/{estudiante_id}/contexto/{semestre}/progreso", summary="Progreso del F3")
def contexto_progreso(estudiante_id: int, semestre: str, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.CONTEXTO, Accion.LEER)
    svc.check_semestre(semestre)
    return svc.context_progress(db, svc.get_context(db, estudiante_id, semestre))


@router.patch("/estudiantes/{estudiante_id}/contexto/{semestre}/resumen", summary="Resumen, factores protectores y de riesgo")
def contexto_resumen(estudiante_id: int, semestre: str, body: sch.ContextoResumenIn, request: Request,
                     db: Session = Depends(get_db), user: Usuario = Depends(_BIENESTAR)):
    est = assert_can(db, user, estudiante_id, Recurso.CONTEXTO, Accion.ESCRIBIR)
    svc.check_semestre(semestre)
    ctx, _ = svc.create_context(db, est, user, semestre, strict=False)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ctx, k, v)
    audit.log(db, user, AccionB.CONTEXTO_MODIFICADO, "contexto_universitario", ctx.id, {"seccion": "resumen"}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.context_progress(db, ctx)


def _ctx_for_write(db: Session, user: Usuario, est_id: int, semestre: str):
    est = _write_ctx(db, user, est_id, aporte_coordinador=True)
    svc.check_semestre(semestre)
    if str(user.rol) == Rol.BIENESTAR:
        ctx, _ = svc.create_context(db, est, user, semestre, strict=False)
    else:
        ctx = _ctx_or_404(db, est_id, semestre)
    return est, ctx


def _make_escenario_patch(esc: Escenario, schema):
    def endpoint(estudiante_id: int, semestre: str, body: schema, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(_ESCRIBIR_CTX)):
        est, ctx = _ctx_for_write(db, user, estudiante_id, semestre)
        svc.save_scenario(db, ctx, esc, body)
        audit.log(db, user, AccionB.CONTEXTO_MODIFICADO, "contexto_universitario", ctx.id, {"escenario": str(esc)},
                  request=request, estudiante_id=est.id)
        db.commit()
        return svc.context_progress(db, ctx)

    endpoint.__name__ = f"contexto_patch_{str(esc).lower()}"
    router.add_api_route(f"/estudiantes/{{estudiante_id}}/contexto/{{semestre}}/escenarios/{esc.value}", endpoint,
                         methods=["PATCH"], summary=f"Guardar el escenario {esc.value} (marcar `aplica` y detallar)")


for _e, _sc in list(sch.ESCENARIO_IN.items()):
    _make_escenario_patch(_e, _sc)


@router.patch("/estudiantes/{estudiante_id}/contexto/{semestre}/docentes", summary="Faceta transversal: docentes")
def contexto_docentes(estudiante_id: int, semestre: str, body: sch.DocentesIn, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(_ESCRIBIR_CTX)):
    est, ctx = _ctx_for_write(db, user, estudiante_id, semestre)
    svc.save_docentes(db, ctx, user, body)
    audit.log(db, user, AccionB.CONTEXTO_MODIFICADO, "contexto_universitario", ctx.id, {"seccion": "docentes"}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.context_view(db, ctx)["docentes"]


@router.patch("/estudiantes/{estudiante_id}/contexto/{semestre}/evaluacion", summary="Faceta transversal: evaluación")
def contexto_evaluacion(estudiante_id: int, semestre: str, body: sch.EvaluacionCtxIn, request: Request,  # type: ignore[valid-type]
                        db: Session = Depends(get_db), user: Usuario = Depends(_ESCRIBIR_CTX)):
    est, ctx = _ctx_for_write(db, user, estudiante_id, semestre)
    svc.save_evaluacion(db, ctx, body)
    audit.log(db, user, AccionB.CONTEXTO_MODIFICADO, "contexto_universitario", ctx.id, {"seccion": "evaluacion"}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.context_view(db, ctx)["evaluacion"]


# ============================================================================ F4
_BARR_W = require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE)


def _own_or_bienestar(user: Usuario, row) -> None:
    if str(user.rol) == Rol.ESTUDIANTE and row.registrada_por_id != user.id:
        raise Forbidden("Usted puede modificar solo lo que usted registró. Pida a Bienestar el cambio.", "SOLO_PROPIOS")


@router.get("/estudiantes/{estudiante_id}/barreras", summary="Mapa de barreras (F4)")
def barreras_listar(estudiante_id: int, tipo_barrera: TipoBarrera | None = None, escenario: Escenario | None = None,
                    estado: EstadoBarrera | None = None, semestre_academico: str | None = None,
                    db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.BARRERAS, Accion.LEER)
    stmt = select(BarreraIdentificada).where(BarreraIdentificada.estudiante_id == estudiante_id)
    if tipo_barrera:
        stmt = stmt.where(BarreraIdentificada.tipo_barrera == tipo_barrera)
    if escenario:
        stmt = stmt.where(BarreraIdentificada.escenario == escenario)
    if estado:
        stmt = stmt.where(BarreraIdentificada.estado == estado)
    if semestre_academico:
        stmt = stmt.where(BarreraIdentificada.semestre_academico == semestre_academico)
    rows = db.scalars(stmt.order_by(BarreraIdentificada.id)).all()
    return {"items": [svc.barrier_view(db, b) for b in rows], "total": len(rows)}


@router.post("/estudiantes/{estudiante_id}/barreras", status_code=201, summary="Registrar una barrera")
def barrera_crear(estudiante_id: int, body: sch.BarreraIn, request: Request, db: Session = Depends(get_db),
                  user: Usuario = Depends(_BARR_W)):
    accion = Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR
    est = assert_can(db, user, estudiante_id, Recurso.BARRERAS, accion)
    b = svc.create_barrier(db, est, user, body)
    audit.log(db, user, AccionB.BARRERA_CREADA, "barrera_identificada", b.id, {"tipo": str(b.tipo_barrera)}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.barrier_view(db, b)


def _barrier_access(db: Session, user: Usuario, barrera_id: int, accion: Accion):
    b = svc.get_barrier(db, barrera_id)
    assert_can(db, user, b.estudiante_id, Recurso.BARRERAS, accion)
    return b


@router.get("/barreras/{barrera_id}", summary="Detalle de una barrera")
def barrera_ver(barrera_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    return svc.barrier_view(db, _barrier_access(db, user, barrera_id, Accion.LEER))


@router.patch("/barreras/{barrera_id}", summary="Modificar una barrera")
def barrera_modificar(barrera_id: int, body: sch.BarreraPatch, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(_BARR_W)):
    b = _barrier_access(db, user, barrera_id, Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR)
    _own_or_bienestar(user, b)
    svc.update_barrier(db, b, body)
    audit.log(db, user, AccionB.BARRERA_MODIFICADA, "barrera_identificada", b.id, None, request=request, estudiante_id=b.estudiante_id)
    db.commit()
    return svc.barrier_view(db, b)


@router.delete("/barreras/{barrera_id}", summary="Archivar una barrera (soft delete)")
def barrera_eliminar(barrera_id: int, request: Request, motivo: str = Query(..., min_length=3, max_length=500),
                     db: Session = Depends(get_db), user: Usuario = Depends(_BARR_W)):
    b = _barrier_access(db, user, barrera_id, Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR)
    _own_or_bienestar(user, b)
    soft_delete_obj(b, user, motivo)
    audit.log(db, user, AccionB.BARRERA_ELIMINADA, "barrera_identificada", b.id, {"motivo": motivo}, request=request,
              estudiante_id=b.estudiante_id)
    db.commit()
    return {"detail": "Barrera archivada.", "id": b.id}


@router.post("/barreras/{barrera_id}/persistente", summary="Marcar barrera persistente tras DUA (paso 7)")
def barrera_persistente(barrera_id: int, body: sch.PersistenteIn, request: Request, db: Session = Depends(get_db),
                        user: Usuario = Depends(_BIENESTAR)):
    b = _barrier_access(db, user, barrera_id, Accion.ESCRIBIR)
    svc.mark_persistent(db, b)
    audit.log(db, user, AccionB.BARRERA_PERSISTENTE, "barrera_identificada", b.id,
              {"observacion": bool(body.observacion)}, request=request, estudiante_id=b.estudiante_id)
    db.commit()
    return svc.barrier_view(db, b)


# ============================================================================ F5
@router.get("/estudiantes/{estudiante_id}/facilitadores", summary="Mapa de facilitadores (F5)")
def facilitadores_listar(estudiante_id: int, tipo_facilitador: TipoFacilitador | None = None, db: Session = Depends(get_db),
                         user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.FACILITADORES, Accion.LEER)
    stmt = select(Facilitador).where(Facilitador.estudiante_id == estudiante_id)
    if tipo_facilitador:
        stmt = stmt.where(Facilitador.tipo_facilitador == tipo_facilitador)
    rows = db.scalars(stmt.order_by(Facilitador.id)).all()
    return {"items": [svc.facilitator_view(db, f) for f in rows], "total": len(rows)}


@router.post("/estudiantes/{estudiante_id}/facilitadores", status_code=201, summary="Registrar un facilitador")
def facilitador_crear(estudiante_id: int, body: sch.FacilitadorIn, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(_BARR_W)):
    accion = Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR
    est = assert_can(db, user, estudiante_id, Recurso.FACILITADORES, accion)
    f = svc.create_facilitator(db, est, user, body)
    audit.log(db, user, AccionB.FACILITADOR_CREADO, "facilitador", f.id, {"tipo": str(f.tipo_facilitador)}, request=request,
              estudiante_id=est.id)
    db.commit()
    return svc.facilitator_view(db, f)


def _fac_access(db: Session, user: Usuario, fid: int, accion: Accion):
    f = svc.get_facilitator(db, fid)
    assert_can(db, user, f.estudiante_id, Recurso.FACILITADORES, accion)
    return f


@router.get("/facilitadores/{facilitador_id}", summary="Detalle de un facilitador")
def facilitador_ver(facilitador_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    return svc.facilitator_view(db, _fac_access(db, user, facilitador_id, Accion.LEER))


@router.patch("/facilitadores/{facilitador_id}", summary="Modificar un facilitador (y sus vínculos)")
def facilitador_modificar(facilitador_id: int, body: sch.FacilitadorPatch, request: Request, db: Session = Depends(get_db),
                          user: Usuario = Depends(_BARR_W)):
    f = _fac_access(db, user, facilitador_id, Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR)
    _own_or_bienestar(user, _Reg(f))
    svc.update_facilitator(db, f, body)
    audit.log(db, user, AccionB.FACILITADOR_MODIFICADO, "facilitador", f.id, None, request=request, estudiante_id=f.estudiante_id)
    db.commit()
    return svc.facilitator_view(db, f)


@router.put("/facilitadores/{facilitador_id}/barreras", summary="Reemplazar las barreras que mitiga")
def facilitador_vinculos(facilitador_id: int, body: sch.VinculosIn, request: Request, db: Session = Depends(get_db),
                         user: Usuario = Depends(_BARR_W)):
    f = _fac_access(db, user, facilitador_id, Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR)
    _own_or_bienestar(user, _Reg(f))
    svc.set_links(db, f, body.barrera_ids, reemplazar=True)
    audit.log(db, user, AccionB.FACILITADOR_MODIFICADO, "facilitador", f.id, {"vinculos": len(body.barrera_ids)}, request=request,
              estudiante_id=f.estudiante_id)
    db.commit()
    return svc.facilitator_view(db, f)


@router.delete("/facilitadores/{facilitador_id}", summary="Archivar un facilitador (soft delete)")
def facilitador_eliminar(facilitador_id: int, request: Request, motivo: str = Query(..., min_length=3, max_length=500),
                         db: Session = Depends(get_db), user: Usuario = Depends(_BARR_W)):
    f = _fac_access(db, user, facilitador_id, Accion.ESCRIBIR if str(user.rol) == Rol.BIENESTAR else Accion.APORTAR)
    _own_or_bienestar(user, _Reg(f))
    soft_delete_obj(f, user, motivo)
    audit.log(db, user, AccionB.FACILITADOR_ELIMINADO, "facilitador", f.id, {"motivo": motivo}, request=request,
              estudiante_id=f.estudiante_id)
    db.commit()
    return {"detail": "Facilitador archivado.", "id": f.id}


class _Reg:
    """Adapta Facilitador (campo `registrado_por_id`) a la verificación de autoría."""

    def __init__(self, f):
        self.registrada_por_id = f.registrado_por_id


@router.get("/estudiantes/{estudiante_id}/resumen-barrera-facilitador", summary="Vista cruzada barrera-facilitador")
def resumen_cruzado(estudiante_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.BARRERAS, Accion.LEER)
    assert_can(db, user, estudiante_id, Recurso.FACILITADORES, Accion.LEER)
    return svc.cross_summary(db, estudiante_id)
