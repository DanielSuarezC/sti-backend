"""Router de trayectoria academica (D9), hitos (M8) y F10 (RF-34/35, HU-17) del STI.

# OWNER: slice C3
Rutas bajo `/estudiantes/{estudiante_id}/...`; en lugar del id numerico se acepta `mi` para el propio estudiante.
Documentado en `docs/api/slice_c3.md`.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import (
    Accion,
    Recurso,
    assert_can,
    get_db,
    get_own_estudiante,
    require_roles_consent,
)
from app.core.errors import Forbidden, NotFound, Unprocessable
from app.models.enums import Rol
from app.models.usuarios import Estudiante, Usuario
from app.schemas.common import MessageResponse
from app.schemas.trayectoria import (
    DIMENSION_SCHEMAS,
    ActualizacionPlanPatch,
    DimensionNombre,
    F10Aprobar,
    F10Generar,
    F10Out,
    F10ResumenOut,
    F10TrayectoriaPatch,
    HitoCrear,
    HitoOut,
    HitoPatch,
    NotaCrear,
    NotaOut,
    NotaPatch,
    NotaRechazar,
    TrayectoriaCrear,
    TrayectoriaListaOut,
    TrayectoriaOut,
    TrayectoriaPatch,
)
from app.services import f10 as svc_f10
from app.services import trayectoria as svc

# OWNER: slice C3
router = APIRouter(prefix="/estudiantes", tags=["trayectoria-f10"])

_lectura = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))
_bienestar = Depends(require_roles_consent(Rol.BIENESTAR))
_estudiante = Depends(require_roles_consent(Rol.ESTUDIANTE))
_notas = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE))


def _eid(db: Session, user: Usuario, raw: str) -> int:
    """`mi` -> estudiante propio; numero -> id (el alcance lo valida `assert_can`)."""
    if raw == "mi":
        est = get_own_estudiante(db, user)
        if est is None:
            raise NotFound("No encontramos su perfil de estudiante.", "ESTUDIANTE_NO_ENCONTRADO")
        return est.id
    if not raw.isdigit():
        raise Unprocessable("El identificador del estudiante debe ser un número o 'mi'.", "ESTUDIANTE_INVALIDO")
    return int(raw)


def _leer(db: Session, user: Usuario, raw: str) -> Estudiante:
    return assert_can(db, user, _eid(db, user, raw), Recurso.TRAYECTORIA, Accion.LEER)


def _escribir(db: Session, user: Usuario, raw: str) -> Estudiante:
    return assert_can(db, user, _eid(db, user, raw), Recurso.TRAYECTORIA, Accion.ESCRIBIR)


# ============================================================================ trayectoria por semestre
@router.post("/{estudiante_id}/trayectoria", response_model=TrayectoriaOut, status_code=201)
def crear_trayectoria(estudiante_id: str, body: TrayectoriaCrear, request: Request, db: Session = Depends(get_db),
                      user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    tray = svc.crear_trayectoria(db, est, body, user)
    audit.log(db, user, "TRAYECTORIA_CREADA", "trayectoria_academica", tray.id, {"semestre": tray.semestre_academico},
              request=request, estudiante_id=est.id)
    db.commit()
    return svc.serializar_trayectoria(tray)


@router.get("/{estudiante_id}/trayectoria", response_model=TrayectoriaListaOut)
def listar_trayectoria(estudiante_id: str, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    return {"estudiante_id": est.id, "resumen": svc.resumen_trayectoria(db, est),
            "trayectorias": [svc.serializar_trayectoria(t) for t in svc.listar_trayectorias(db, est.id)],
            "hitos": svc.listar_hitos(db, est.id)}


@router.get("/{estudiante_id}/trayectoria/resumen")
def resumen(estudiante_id: str, db: Session = Depends(get_db), user: Usuario = _lectura):
    return svc.resumen_trayectoria(db, _leer(db, user, estudiante_id))


@router.get("/{estudiante_id}/trayectoria/{semestre}", response_model=TrayectoriaOut)
def ver_trayectoria(estudiante_id: str, semestre: str, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    return svc.serializar_trayectoria(svc.get_trayectoria_or_404(db, est.id, semestre))


@router.patch("/{estudiante_id}/trayectoria/{semestre}", response_model=TrayectoriaOut)
def editar_trayectoria(estudiante_id: str, semestre: str, body: TrayectoriaPatch, request: Request,
                       db: Session = Depends(get_db), user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    tray = svc.actualizar_trayectoria(db, svc.get_trayectoria_or_404(db, est.id, semestre), body)
    audit.log(db, user, "TRAYECTORIA_ACTUALIZADA", "trayectoria_academica", tray.id, {"semestre": semestre},
              request=request, estudiante_id=est.id)
    db.commit()
    return svc.serializar_trayectoria(tray)


@router.patch("/{estudiante_id}/trayectoria/{semestre}/dimensiones/{dimension}", response_model=TrayectoriaOut)
def editar_dimension(estudiante_id: str, semestre: str, dimension: DimensionNombre, body: dict, request: Request,
                     db: Session = Depends(get_db), user: Usuario = _bienestar):
    """Edita UNA de las 9 dimensiones (parcial). El cuerpo es el de la dimension (ver docs)."""
    est = _escribir(db, user, estudiante_id)
    try:
        datos = DIMENSION_SCHEMAS[dimension].model_validate(body).model_dump(exclude_unset=True, mode="json")
    except ValueError as exc:  # pydantic.ValidationError hereda de ValueError
        raise Unprocessable(f"Datos inválidos para la dimensión {dimension}: {_resumen_error(exc)}", "DATOS_INVALIDOS")
    tray = svc.get_trayectoria_or_404(db, est.id, semestre)
    svc.aplicar_dimension(db, tray, dimension, datos)
    audit.log(db, user, "TRAYECTORIA_DIMENSION_ACTUALIZADA", "trayectoria_academica", tray.id,
              {"semestre": semestre, "dimension": dimension}, request=request, estudiante_id=est.id)
    db.commit()
    return svc.serializar_trayectoria(tray)


def _resumen_error(exc: Exception) -> str:
    errs = getattr(exc, "errors", lambda: [])()
    return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in errs[:3]) or str(exc)


# ============================================================================ hitos
@router.get("/{estudiante_id}/hitos", response_model=list[HitoOut])
def listar_hitos(estudiante_id: str, db: Session = Depends(get_db), user: Usuario = _lectura):
    return svc.listar_hitos(db, _leer(db, user, estudiante_id).id)


@router.post("/{estudiante_id}/hitos", response_model=HitoOut, status_code=201)
def crear_hito(estudiante_id: str, body: HitoCrear, request: Request, db: Session = Depends(get_db),
               user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    h = svc.crear_hito(db, est, body, user)
    audit.log(db, user, "HITO_TRAYECTORIA_CREADO", "hito_trayectoria", h.id, {"tipo": str(body.tipo_hito)},
              request=request, estudiante_id=est.id)
    db.commit()
    return next(x for x in svc.listar_hitos(db, est.id) if x["id"] == h.id)


@router.patch("/{estudiante_id}/hitos/{hito_id}", response_model=HitoOut)
def editar_hito(estudiante_id: str, hito_id: int, body: HitoPatch, db: Session = Depends(get_db),
                user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    h = svc.get_hito_or_404(db, est.id, hito_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None or k == "descripcion":
            setattr(h, k, v)
    db.commit()
    return next(x for x in svc.listar_hitos(db, est.id) if x["id"] == h.id)


@router.delete("/{estudiante_id}/hitos/{hito_id}", response_model=MessageResponse)
def eliminar_hito(estudiante_id: str, hito_id: int, request: Request, db: Session = Depends(get_db),
                  user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    h = svc.get_hito_or_404(db, est.id, hito_id)
    h.soft_delete(user.id, "Eliminado por Bienestar")
    audit.log(db, user, "HITO_TRAYECTORIA_ELIMINADO", "hito_trayectoria", h.id, None, request=request,
              estudiante_id=est.id)
    db.commit()
    return MessageResponse(detail="El hito se archivó.")


# ============================================================================ F10
@router.post("/{estudiante_id}/f10/borrador", response_model=F10Out, status_code=201)
def generar_borrador(estudiante_id: str, body: F10Generar | None = None, db: Session = Depends(get_db),
                     user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    body = body or F10Generar()
    f = svc_f10.generar_borrador(db, est, user, body.semestre_origen, body.semestre_destino)
    db.commit()
    return svc_f10.serializar_f10(db, f, user)


@router.get("/{estudiante_id}/f10", response_model=list[F10ResumenOut])
def listar_f10(estudiante_id: str, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    return [svc_f10.serializar_resumen(db, f) for f in svc_f10.listar_f10(db, est.id)]


@router.get("/{estudiante_id}/f10/{f10_id}", response_model=F10Out)
def ver_f10(estudiante_id: str, f10_id: int, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    return svc_f10.serializar_f10(db, f, user)


@router.get("/{estudiante_id}/f10/{f10_id}/actualizacion-plan")
def ver_actualizacion_plan(estudiante_id: str, f10_id: int, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    return {"f10_id": f.id, "estado": str(f.estado), "plan_id": f.plan_id, "plan_siguiente_id": f.plan_siguiente_id,
            **(f.actualizacion_plan or {"items": []})}


@router.patch("/{estudiante_id}/f10/{f10_id}/actualizacion-plan")
def editar_actualizacion_plan(estudiante_id: str, f10_id: int, body: ActualizacionPlanPatch, db: Session = Depends(get_db),
                              user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    adv = svc_f10.actualizar_plan(db, f, body, user)
    db.commit()
    return {"f10_id": f.id, "estado": str(f.estado), "advertencias": adv, **f.actualizacion_plan}


@router.get("/{estudiante_id}/f10/{f10_id}/trayectoria")
def ver_f10_trayectoria(estudiante_id: str, f10_id: int, db: Session = Depends(get_db), user: Usuario = _lectura):
    est = _leer(db, user, estudiante_id)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    return {"f10_id": f.id, "estado": str(f.estado), "trayectoria": svc_f10.componente_trayectoria(db, f),
            "necesidades_anticipadas": f.necesidades_anticipadas or [], "proyeccion": f.proyeccion}


@router.patch("/{estudiante_id}/f10/{f10_id}/trayectoria")
def editar_f10_trayectoria(estudiante_id: str, f10_id: int, body: F10TrayectoriaPatch, db: Session = Depends(get_db),
                           user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    adv = svc_f10.actualizar_trayectoria_f10(db, f, est, body, user)
    db.commit()
    return {"f10_id": f.id, "estado": str(f.estado), "advertencias": adv,
            "trayectoria": svc_f10.componente_trayectoria(db, f), "necesidades_anticipadas": f.necesidades_anticipadas,
            "proyeccion": f.proyeccion}


@router.post("/{estudiante_id}/f10/{f10_id}/aprobar")
def aprobar_f10(estudiante_id: str, f10_id: int, request: Request, body: F10Aprobar | None = None,
                db: Session = Depends(get_db), user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    """Bienestar y el Estudiante aprueban por separado; al segundo sello el F10 queda APROBADO."""
    eid = _eid(db, user, estudiante_id)
    if str(user.rol) == Rol.ESTUDIANTE:
        est = assert_can(db, user, eid, Recurso.NOTAS_CONTINUIDAD, Accion.APROBAR)
    else:
        est = assert_can(db, user, eid, Recurso.TRAYECTORIA, Accion.ESCRIBIR)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    res = svc_f10.aprobar(db, f, est, user, (body.comentario if body else None))
    db.commit()
    return {**svc_f10.serializar_resumen(db, f), **res}


# ============================================================================ notas de continuidad (RF-35)
def _puede_escribir_nota(db: Session, user: Usuario, eid: int) -> Estudiante:
    """Bienestar (matriz: CRUD) o el propio estudiante redactando sus notas (aporte propio)."""
    if str(user.rol) == Rol.ESTUDIANTE:
        return assert_can(db, user, eid, Recurso.NOTAS_CONTINUIDAD, Accion.LEER)
    return assert_can(db, user, eid, Recurso.NOTAS_CONTINUIDAD, Accion.ESCRIBIR)


def _nota_editable(db: Session, user: Usuario, n, est: Estudiante) -> None:
    if str(user.rol) == Rol.ESTUDIANTE:
        if n.elaborada_por_id != user.id:
            raise Forbidden("Solo puede editar las notas que usted redactó.", "ACCESO_DENEGADO")
    elif not svc_f10.nota_visible(db, n, user, est):
        raise NotFound("No encontramos esa nota de continuidad.", "NOTA_NO_ENCONTRADA")


@router.get("/{estudiante_id}/f10/{f10_id}/notas", response_model=list[NotaOut])
def listar_notas(estudiante_id: str, f10_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = _notas):
    eid = _eid(db, user, estudiante_id)
    est = assert_can(db, user, eid, Recurso.NOTAS_CONTINUIDAD, Accion.LEER)
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    audit.log(db, user, audit.Accion.ACCESO_NOTAS_CONTINUIDAD, "nota_continuidad", None, {"f10_id": f.id},
              request=request, estudiante_id=est.id)
    db.commit()
    return [svc_f10.serializar_nota(db, n, user) for n in svc_f10.notas_visibles(db, f, user)]


@router.post("/{estudiante_id}/f10/{f10_id}/notas", response_model=NotaOut, status_code=201)
def crear_nota(estudiante_id: str, f10_id: int, body: NotaCrear, db: Session = Depends(get_db),
               user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    est = _puede_escribir_nota(db, user, _eid(db, user, estudiante_id))
    f = svc_f10.get_f10_or_404(db, est.id, f10_id)
    n = svc_f10.crear_nota(db, f, user, body.contenido, body.destinatario)
    db.commit()
    return svc_f10.serializar_nota(db, n, user)


@router.patch("/{estudiante_id}/f10/{f10_id}/notas/{nota_id}", response_model=NotaOut)
def editar_nota(estudiante_id: str, f10_id: int, nota_id: int, body: NotaPatch, db: Session = Depends(get_db),
                user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    est = _puede_escribir_nota(db, user, _eid(db, user, estudiante_id))
    n = svc_f10.get_nota_or_404(db, svc_f10.get_f10_or_404(db, est.id, f10_id), nota_id)
    _nota_editable(db, user, n, est)
    adv = svc_f10.editar_nota(db, n, user, body.contenido, body.destinatario)
    db.commit()
    return svc_f10.serializar_nota(db, n, user, adv)


@router.delete("/{estudiante_id}/f10/{f10_id}/notas/{nota_id}", response_model=MessageResponse)
def eliminar_nota(estudiante_id: str, f10_id: int, nota_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    est = _puede_escribir_nota(db, user, _eid(db, user, estudiante_id))
    n = svc_f10.get_nota_or_404(db, svc_f10.get_f10_or_404(db, est.id, f10_id), nota_id)
    _nota_editable(db, user, n, est)
    n.soft_delete(user.id, "Eliminada por su autor")
    audit.log(db, user, "NOTA_CONTINUIDAD_ELIMINADA", "nota_continuidad", n.id, None, estudiante_id=est.id)
    db.commit()
    return MessageResponse(detail="La nota se archivó.")


@router.post("/{estudiante_id}/f10/{f10_id}/notas/{nota_id}/enviar", response_model=NotaOut)
def enviar_nota(estudiante_id: str, f10_id: int, nota_id: int, db: Session = Depends(get_db), user: Usuario = _bienestar):
    est = _escribir(db, user, estudiante_id)
    n = svc_f10.get_nota_or_404(db, svc_f10.get_f10_or_404(db, est.id, f10_id), nota_id)
    _nota_editable(db, user, n, est)
    svc_f10.enviar_nota(db, n, user, est)
    db.commit()
    return svc_f10.serializar_nota(db, n, user)


@router.post("/{estudiante_id}/f10/{f10_id}/notas/{nota_id}/aprobar", response_model=NotaOut)
def aprobar_nota(estudiante_id: str, f10_id: int, nota_id: int, db: Session = Depends(get_db), user: Usuario = _estudiante):
    est = assert_can(db, user, _eid(db, user, estudiante_id), Recurso.NOTAS_CONTINUIDAD, Accion.APROBAR)
    n = svc_f10.get_nota_or_404(db, svc_f10.get_f10_or_404(db, est.id, f10_id), nota_id)
    svc_f10.aprobar_nota(db, n, user)
    db.commit()
    return svc_f10.serializar_nota(db, n, user)


@router.post("/{estudiante_id}/f10/{f10_id}/notas/{nota_id}/rechazar", response_model=NotaOut)
def rechazar_nota(estudiante_id: str, f10_id: int, nota_id: int, body: NotaRechazar, db: Session = Depends(get_db),
                  user: Usuario = _estudiante):
    est = assert_can(db, user, _eid(db, user, estudiante_id), Recurso.NOTAS_CONTINUIDAD, Accion.APROBAR)
    n = svc_f10.get_nota_or_404(db, svc_f10.get_f10_or_404(db, est.id, f10_id), nota_id)
    svc_f10.rechazar_nota(db, n, user, body.motivo)
    db.commit()
    return svc_f10.serializar_nota(db, n, user)


@router.get("/{estudiante_id}/notas-continuidad", response_model=list[NotaOut])
def notas_para_nuevos_actores(estudiante_id: str, semestre_destino: str, request: Request, db: Session = Depends(get_db),
                              user: Usuario = _notas):
    """Notas APROBADAS dirigidas al semestre que inicia, segun el alcance del rol (Bienestar/Coordinador nuevos)."""
    eid = _eid(db, user, estudiante_id)
    est = assert_can(db, user, eid, Recurso.NOTAS_CONTINUIDAD, Accion.LEER)
    audit.log(db, user, audit.Accion.ACCESO_NOTAS_CONTINUIDAD, "nota_continuidad", None,
              {"semestre_destino": semestre_destino}, request=request, estudiante_id=est.id)
    db.commit()
    return [svc_f10.serializar_nota(db, n, user)
            for n in svc_f10.notas_aprobadas_destino(db, est.id, semestre_destino, user)]
