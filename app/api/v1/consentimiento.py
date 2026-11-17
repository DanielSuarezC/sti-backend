"""F0 (consentimiento informado) y derechos ARCO. Ver docs/api/slice_b.md.

# OWNER: slice B
Estos endpoints NO exigen F0 firmado (son la excepción a `require_consent`).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, get_own_estudiante, require_roles
from app.core.errors import Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.permissions import can_access_student, get_estudiante_or_404, students_scope_criterion_db
from app.data import f0_texto
from app.models.enums import Rol
from app.models.slice_b import EstadoArco, SolicitudArco, TipoArco
from app.models.usuarios import Estudiante, Usuario
from app.schemas.consentimiento import ArcoGestionIn, ArcoIn, ArcoProrrogaIn, FirmarIn, RevocarIn
from app.services import arco as arco_svc
from app.services import consent as consent_svc
from app.services.b_common import AccionB

router = APIRouter(tags=["consentimiento"])


def _own_student(db: Session, user: Usuario) -> Estudiante:
    est = get_own_estudiante(db, user)
    if est is None:
        raise NotFound("Su cuenta no tiene un perfil de estudiante.", "ESTUDIANTE_NO_ENCONTRADO")
    return est


# ============================================================================ F0
@router.get("/consentimiento/texto", summary="Texto vigente del F0 (público, versionado)")
def texto():
    return f0_texto.as_dict()


@router.get("/consentimiento/mio", summary="Estado de mi consentimiento")
def mio(db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    return consent_svc.state(db, _own_student(db, user))


@router.post("/consentimiento/firmar", status_code=201, summary="Firmar el F0 (estudiante o Bienestar en modalidad asistida)")
def firmar(body: FirmarIn, request: Request, db: Session = Depends(get_db),
           user: Usuario = Depends(require_roles(Rol.ESTUDIANTE, Rol.BIENESTAR))):
    if str(user.rol) == Rol.ESTUDIANTE:
        if body.estudiante_id is not None:
            raise Forbidden("Usted solo puede firmar su propio consentimiento.", "ACCESO_DENEGADO")
        est = _own_student(db, user)
    else:
        if body.estudiante_id is None:
            raise Unprocessable("Indique el estudiante (estudiante_id) para la firma asistida.", "ESTUDIANTE_REQUERIDO")
        est = assert_can(db, user, body.estudiante_id, Recurso.DATOS_BASICOS, Accion.ESCRIBIR, require_consent=False)
    consent_svc.sign(
        db, est, user, version_texto=body.version_texto, texto_hash=body.texto_hash, nombre_firmante=body.nombre_firmante,
        acepta_tratamiento_general=body.acepta_tratamiento_general,
        acepta_datos_sensibles_salud=body.acepta_datos_sensibles_salud,
        acepta_compartir_ajustes_docentes=body.acepta_compartir_ajustes_docentes, request=request,
    )
    db.commit()
    return {**consent_svc.state(db, est, staff=str(user.rol) == Rol.BIENESTAR),
            "detail": "Consentimiento firmado. Le enviamos una copia a su correo."}


@router.post("/consentimiento/revocar", summary="Retirar mi consentimiento (RF-07)")
def revocar(body: RevocarIn, request: Request, db: Session = Depends(get_db),
            user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    if not body.confirmar:
        raise Unprocessable(
            "Confirme que quiere retirar su consentimiento: su cuenta se inactivará y sus datos se archivarán.",
            "CONFIRMACION_REQUERIDA",
        )
    out = consent_svc.revoke(db, _own_student(db, user), user, motivo=body.motivo, request=request)
    db.commit()
    out["detail"] = "Retiramos su consentimiento. Su cuenta quedó inactiva y sus datos archivados. No hay consecuencias académicas."
    return out


# ============================================================================ ARCO (antes de /consentimiento/{id} por claridad)
@router.post("/arco/solicitudes", status_code=201, summary="Radicar una solicitud ARCO")
def arco_crear(body: ArcoIn, db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    est = _own_student(db, user)
    s = arco_svc.create_request(db, est, user, body.tipo, body.descripcion)
    db.commit()
    return arco_svc.serialize(s, para_estudiante=True)


@router.get("/arco/mis-solicitudes", summary="Mis solicitudes ARCO")
def arco_mias(db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    est = _own_student(db, user)
    rows = db.scalars(select(SolicitudArco).where(SolicitudArco.estudiante_id == est.id).order_by(SolicitudArco.id.desc())).all()
    return {"items": [arco_svc.serialize(s, para_estudiante=True) for s in rows], "total": len(rows)}


@router.get("/arco/exportar-mis-datos", summary="Descargar mis datos (JSON, descifrados)")
def arco_exportar(request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.ESTUDIANTE))):
    est = _own_student(db, user)
    data = arco_svc.export_student_data(db, est, user)
    audit.log(db, user, AccionB.ARCO_EXPORTACION, "estudiante", est.id, {"tablas": len(data["datos"])},
              request=request, estudiante_id=est.id)
    db.commit()
    return JSONResponse(
        data, headers={"Content-Disposition": f'attachment; filename="mis-datos-sti-{date.today().isoformat()}.json"'}
    )


@router.get("/arco/solicitudes", summary="Bandeja ARCO (Bienestar/Admin)")
def arco_listar(
    params: PageParams = Depends(), estado: EstadoArco | None = None, tipo: TipoArco | None = None,
    vencidas: bool | None = Query(None, description="true: solo abiertas con plazo vencido"),
    db: Session = Depends(get_db), user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN)),
):
    stmt = select(SolicitudArco).where(
        SolicitudArco.estudiante_id.in_(select(Estudiante.id).where(students_scope_criterion_db(db, user)))
    )
    if estado:
        stmt = stmt.where(SolicitudArco.estado == estado)
    if tipo:
        stmt = stmt.where(SolicitudArco.tipo == tipo)
    if vencidas:
        stmt = stmt.where(SolicitudArco.estado.in_([EstadoArco.RECIBIDA, EstadoArco.EN_TRAMITE]),
                          SolicitudArco.fecha_limite < date.today())
    return paginate(db, stmt.order_by(SolicitudArco.fecha_limite, SolicitudArco.id), params, arco_svc.serialize)


def _staff_request(db: Session, user: Usuario, solicitud_id: int) -> SolicitudArco:
    s = arco_svc.get_request(db, solicitud_id)
    if not can_access_student(db, user, s.estudiante_id):
        raise Forbidden("No tiene acceso a esta solicitud.", "ACCESO_DENEGADO")
    return s


@router.get("/arco/solicitudes/{solicitud_id}", summary="Detalle de una solicitud ARCO")
def arco_detalle(solicitud_id: int, db: Session = Depends(get_db),
                 user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN, Rol.ESTUDIANTE))):
    s = arco_svc.get_request(db, solicitud_id)
    if str(user.rol) == Rol.ESTUDIANTE:
        if s.solicitante_id != user.id:
            raise NotFound("No encontramos la solicitud indicada.", "ARCO_NO_ENCONTRADA")
        return arco_svc.serialize(s, para_estudiante=True)
    return arco_svc.serialize(_staff_request(db, user, solicitud_id))


@router.patch("/arco/solicitudes/{solicitud_id}", summary="Gestionar una solicitud ARCO")
def arco_gestionar(solicitud_id: int, body: ArcoGestionIn, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))):
    s = _staff_request(db, user, solicitud_id)
    arco_svc.manage_request(db, s, user, estado=body.estado, respuesta=body.respuesta)
    db.commit()
    return arco_svc.serialize(s)


@router.post("/arco/solicitudes/{solicitud_id}/prorrogar", summary="Prorrogar el plazo (una vez)")
def arco_prorrogar(solicitud_id: int, body: ArcoProrrogaIn, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))):
    s = _staff_request(db, user, solicitud_id)
    arco_svc.extend_deadline(db, s, user, body.motivo)
    db.commit()
    return arco_svc.serialize(s)


# ============================================================================ estado del F0 de un estudiante
@router.get("/consentimiento/{estudiante_id}", summary="Estado del F0 de un estudiante (Bienestar/Admin)")
def estado_estudiante(estudiante_id: int, request: Request, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))):
    est = get_estudiante_or_404(db, estudiante_id)
    if not can_access_student(db, user, est.id):
        raise Forbidden("No tiene acceso a este estudiante.", "ACCESO_DENEGADO")
    return consent_svc.state(db, est, staff=True)
