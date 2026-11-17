"""Router F8 - Seguimiento por cortes con semaforo (M6). Rutas bajo `/planes/{plan_id}/seguimiento...` y `/planes/{plan_id}/semaforo`.

# OWNER: slice C2
Contrato completo en docs/api/slice_c2.md. La logica vive en `services/seguimiento.py` y `services/semaforo.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import (
    Accion,
    Recurso,
    assert_can,
    docente_ajuste_ids,
    get_db,
    require_roles_consent,
)
from app.core.errors import AppError, NotFound
from app.models.enums import Corte, Rol
from app.models.seguimiento import EvidenciaEfectividad, RegistroSeguimiento, RegistroSeguimientoAjuste
from app.models.usuarios import Usuario
from app.schemas.seguimiento import (
    BarreraEmergenteIn,
    ConcertacionResolver,
    EvidenciaIn,
    PercepcionIn,
    RedisenoIn,
    RegistroAjusteIn,
    RegistroSeguimientoIn,
    SeguimientoAbrir,
    SeguimientoPatch,
)
from app.services import seguimiento as svc
from app.services import semaforo as sem
from app.services.evaluacion import tendencia

router = APIRouter(prefix="/planes", tags=["seguimiento"])

_LEER = (Rol.BIENESTAR, Rol.COORDINADOR, Rol.DOCENTE, Rol.ESTUDIANTE, Rol.FAMILIAR, Rol.ADMIN)


def _ctx(db: Session, user: Usuario, plan_id: int, accion: Accion = Accion.LEER):
    plan = svc.get_plan_or_404(db, plan_id)
    est = assert_can(db, user, plan.estudiante_id, Recurso.SEGUIMIENTO, accion)
    return plan, est


def _vista(db: Session, user: Usuario, plan_id: int) -> tuple[str, set[int] | None]:
    if str(user.rol) == Rol.DOCENTE:
        return "docente", docente_ajuste_ids(db, user, plan_id)
    return "completa", None


def _seg_ajuste(db: Session, plan, corte: Corte, ajuste_id: int):
    seg = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    return seg, svc.exigir_ajuste_del_plan(db, plan, ajuste_id)


# ----------------------------------------------------------------------------- cortes
@router.get("/{plan_id}/seguimiento")
def listar_cortes(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*_LEER))):
    """Los 3 cortes (C1/C2/C3) del calendario activo con su estado ABIERTO | CERRADO | FUTURO."""
    plan, est = _ctx(db, user, plan_id)
    vista, ids = _vista(db, user, plan_id)
    cal = svc.calendario_para(db, plan, est)  # 409 CALENDARIO_NO_CONFIGURADO
    return {
        "plan_id": plan.id, "plan_estado": str(plan.estado), "semestre": plan.semestre_academico,
        "calendario": {"id": cal.id, "semestre_academico": cal.semestre_academico, "programa_id": cal.programa_id},
        "cortes": svc.estado_cortes(db, plan, cal, ajuste_ids=ids),
        "rojos_sin_rediseno": [] if vista == "docente" else [r.ajuste_id for r in sem.rojos_sin_rediseno(db, plan.id)],
    }


@router.post("/{plan_id}/seguimiento/{corte}")
def abrir_corte(plan_id: int, corte: Corte, request: Request, body: SeguimientoAbrir | None = None,
                db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Crea (201) o devuelve (200) el seguimiento del corte. Solo planes en IMPLEMENTACION/SEGUIMIENTO."""
    from fastapi.responses import JSONResponse

    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    datos = body.model_dump(exclude_none=True) if body else {}
    s, creado = svc.abrir_corte(db, plan, est, corte.value, user, datos, request)
    db.commit()
    out = svc.serializar_corte(db, plan, s)
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(jsonable_encoder(out), status_code=201 if creado else 200)


@router.get("/{plan_id}/seguimiento/{corte}")
def ver_corte(plan_id: int, corte: Corte, db: Session = Depends(get_db),
              user: Usuario = Depends(require_roles_consent(*_LEER))):
    plan, _ = _ctx(db, user, plan_id)
    vista, ids = _vista(db, user, plan_id)
    return svc.serializar_corte(db, plan, svc.get_seguimiento_or_404(db, plan.id, corte.value), ajuste_ids=ids, vista=vista)


@router.patch("/{plan_id}/seguimiento/{corte}")
def actualizar_corte(plan_id: int, corte: Corte, body: SeguimientoPatch, request: Request, db: Session = Depends(get_db),
                     user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, _ = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    svc.actualizar_corte(db, s, body.model_dump(exclude_unset=True), user, request)
    db.commit()
    return svc.serializar_corte(db, plan, s)


@router.post("/{plan_id}/seguimiento/{corte}/cerrar")
def cerrar_corte(plan_id: int, corte: Corte, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Cierra el corte: exige semaforo en TODOS los ajustes. Devuelve el agregado y «lo que sigue»."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    res = svc.cerrar_corte(db, plan, est, s, user, request)
    db.commit()
    return {**res, "corte": svc.serializar_corte(db, plan, s)}


# ----------------------------------------------------------------------------- por ajuste
@router.put("/{plan_id}/seguimiento/{corte}/ajustes/{ajuste_id}")
def registrar_ajuste(plan_id: int, corte: Corte, ajuste_id: int, body: RegistroAjusteIn, request: Request,
                     db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Bienestar registra implementado/frecuencia/resultado/semaforo. ROJO y AMARILLO disparan sus reglas (RF-29/RF-39)."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s, ajuste = _seg_ajuste(db, plan, corte, ajuste_id)
    reg, res = svc.registrar_ajuste(db, plan, est, s, ajuste, user, body.model_dump(exclude_unset=True), request)
    db.commit()
    return {"registro": sem.serializar_registro(reg), "semaforo": res}


@router.put("/{plan_id}/seguimiento/{corte}/ajustes/{ajuste_id}/percepcion")
def registrar_percepcion(plan_id: int, corte: Corte, ajuste_id: int, body: PercepcionIn, request: Request,
                         db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.ESTUDIANTE))):
    """HU-21: solo el estudiante escribe su percepcion. Nadie mas puede modificarla."""
    plan, _ = _ctx(db, user, plan_id, Accion.PERCEPCION)
    s, ajuste = _seg_ajuste(db, plan, corte, ajuste_id)
    reg = svc.registrar_percepcion(db, plan, s, ajuste, user, body.percepcion, body.comentario, request)
    db.commit()
    return {"registro": sem.serializar_registro(reg)}


@router.post("/{plan_id}/seguimiento/{corte}/ajustes/{ajuste_id}/concertacion")
def resolver_concertacion(plan_id: int, corte: Corte, ajuste_id: int, body: ConcertacionResolver, request: Request,
                          db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Cierra la tarea de concertacion de un ajuste AMARILLO registrando el acuerdo."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s, ajuste = _seg_ajuste(db, plan, corte, ajuste_id)
    reg = _registro(db, s, ajuste.id)
    sem.resolver_concertacion(db, reg, user, body.acuerdo, est, request)
    db.commit()
    return {"registro": sem.serializar_registro(reg)}


@router.post("/{plan_id}/seguimiento/{corte}/ajustes/{ajuste_id}/rediseno")
def registrar_rediseno(plan_id: int, corte: Corte, ajuste_id: int, body: RedisenoIn, request: Request,
                       db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Registra el rediseno de un ajuste en ROJO: desbloquea la apertura del siguiente corte."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s, ajuste = _seg_ajuste(db, plan, corte, ajuste_id)
    reg = _registro(db, s, ajuste.id)
    sem.registrar_rediseno(db, reg, user, est, request=request, **body.model_dump())
    db.commit()
    return {"registro": sem.serializar_registro(reg), "rojos_sin_rediseno": [r.ajuste_id for r in sem.rojos_sin_rediseno(db, plan.id)]}


def _registro(db: Session, seg, ajuste_id: int) -> RegistroSeguimientoAjuste:
    from sqlalchemy import select

    reg = db.scalar(select(RegistroSeguimientoAjuste).where(
        RegistroSeguimientoAjuste.seguimiento_id == seg.id, RegistroSeguimientoAjuste.ajuste_id == ajuste_id))
    if reg is None:
        raise NotFound("Ese ajuste todavía no tiene registro en este corte.", "REGISTRO_NO_ENCONTRADO")
    return reg


# ----------------------------------------------------------------------------- registros, evidencias, barreras
@router.post("/{plan_id}/seguimiento/{corte}/registros", status_code=201)
def agregar_registro(plan_id: int, corte: Corte, body: RegistroSeguimientoIn, request: Request, db: Session = Depends(get_db),
                     user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, _ = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    r = svc.agregar_registro(db, s, body.model_dump(), user, request)
    db.commit()
    return {"id": r.id, "tipo_registro": str(r.tipo_registro), "descripcion_metodologia": r.descripcion_metodologia,
            "fuentes_informacion": r.fuentes_informacion}


@router.delete("/{plan_id}/seguimiento/{corte}/registros/{registro_id}")
def eliminar_registro(plan_id: int, corte: Corte, registro_id: int, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    svc.exigir_abierto(s)
    r = db.get(RegistroSeguimiento, registro_id)
    if r is None or r.seguimiento_id != s.id:
        raise NotFound("No encontramos ese registro.", "REGISTRO_NO_ENCONTRADO")
    svc.soft_delete(db, r, user, "Eliminado por el profesional", est.id, request)
    db.commit()
    return {"detail": "Registro archivado."}


@router.post("/{plan_id}/seguimiento/{corte}/evidencias", status_code=201)
def agregar_evidencia(plan_id: int, corte: Corte, body: EvidenciaIn, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, _ = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    ev = svc.agregar_evidencia(db, s, body.model_dump(), user, request)
    db.commit()
    return svc._evidencia(db, ev)


@router.delete("/{plan_id}/seguimiento/{corte}/evidencias/{evidencia_id}")
def eliminar_evidencia(plan_id: int, corte: Corte, evidencia_id: int, request: Request, db: Session = Depends(get_db),
                       user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    svc.exigir_abierto(s)
    e = db.get(EvidenciaEfectividad, evidencia_id)
    if e is None or e.seguimiento_id != s.id:
        raise NotFound("No encontramos esa evidencia.", "EVIDENCIA_NO_ENCONTRADA")
    svc.soft_delete(db, e, user, "Eliminada por el profesional", est.id, request)
    db.commit()
    return {"detail": "Evidencia archivada."}


@router.post("/{plan_id}/seguimiento/{corte}/barreras-emergentes", status_code=201)
def barrera_emergente(plan_id: int, corte: Corte, body: BarreraEmergenteIn, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR))):
    """Registra una barrera no prevista en el F4: crea BARRERA_IDENTIFICADA y deja la propuesta de ajuste."""
    plan, est = _ctx(db, user, plan_id, Accion.ESCRIBIR)
    s = svc.get_seguimiento_or_404(db, plan.id, corte.value)
    out = svc.registrar_barrera_emergente(db, plan, est, s, user, body.model_dump(), request)
    db.commit()
    return out


# ----------------------------------------------------------------------------- dashboard
@router.get("/{plan_id}/semaforo")
def dashboard_semaforo(plan_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(*_LEER))):
    """Matriz ajuste x corte, tendencia C1->C2->C3, % verde e indicadores D6/D8 (docente: solo sus ajustes, sin indicadores)."""
    plan, est = _ctx(db, user, plan_id)
    vista, ids = _vista(db, user, plan_id)
    m = sem.construir_matriz(db, plan, ids, vista=vista)
    out = {**m, "plan_estado": str(plan.estado), "semestre": plan.semestre_academico, "tendencia": tendencia(db, plan, m)}
    try:
        cal = svc.calendario_para(db, plan, est)
        out["fechas_cortes"] = {k: v.isoformat() for k, v in svc.fechas_cortes(cal).items()}
    except AppError:
        out["fechas_cortes"] = None
    if vista != "docente":
        out["indicadores"] = {"D6": svc.tasa_implementacion(db, plan.id, "C2"), "D8": svc.porcentaje_verde(db, plan.id)}
    return out

