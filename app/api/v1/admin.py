"""Administración (M1): salud, auditoría, jobs diarios, cola de correo, AQ-10 e importación CSV (Vía 3).

# OWNER: slice A. Contrato en `docs/api/slice_a.md`.
"""

from __future__ import annotations

import hmac
from datetime import date

from fastapi import APIRouter, Depends, File, Header, Query, Request, Response, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.deps import get_current_user, get_db, require_roles
from app.core.errors import Forbidden, Unauthorized
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.enums import EstadoEmail, Rol
from app.models.sistema import EmailOutbox, LogAuditoria
from app.models.usuarios import Usuario
from app.schemas.admin import Aq10Update, OutboxRetry, PuntoCorteBody
from app.services import aq10_config, csv_import, health, jobs
from app.services import email as email_service

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN = Depends(require_roles(Rol.ADMIN))
_bearer = HTTPBearer(auto_error=False)
#: claves del detalle de auditoría que nunca se devuelven (defensa adicional; el log ya enmascara al escribir)
_OCULTAR = ("cuerpo", "texto", "contenido", "narrativa", "descripcion", "respuestas", "puntaje", "diagnostico", "password", "token")


# ----------------------------------------------------------------------------- salud
@router.get("/salud")
def salud(db: Session = Depends(get_db), _: Usuario = ADMIN):
    return health.collect_health(db)


# ----------------------------------------------------------------------------- auditoría
def _limpiar(d):
    if isinstance(d, dict):
        return {k: ("***" if any(s in str(k).lower() for s in _OCULTAR) else _limpiar(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [_limpiar(v) for v in d]
    return d


@router.get("/auditoria")
def auditoria(
    request: Request, actor_id: int | None = None, actor_rol: str | None = None, accion: str | None = None,
    entidad: str | None = None, entidad_id: int | None = None, desde: date | None = None, hasta: date | None = None,
    params: PageParams = Depends(), db: Session = Depends(get_db), admin: Usuario = ADMIN,
):
    """Solo Admin. Devuelve quién, qué, cuándo y sobre qué; nunca cuerpos con datos sensibles."""
    from datetime import UTC, datetime, time, timedelta

    stmt = select(LogAuditoria).order_by(LogAuditoria.id.desc())
    if actor_id is not None:
        stmt = stmt.where(LogAuditoria.actor_id == actor_id)
    if actor_rol:
        stmt = stmt.where(LogAuditoria.actor_rol == actor_rol.upper())
    if accion:
        stmt = stmt.where(LogAuditoria.accion == accion)
    if entidad:
        stmt = stmt.where(LogAuditoria.entidad == entidad)
    if entidad_id is not None:
        stmt = stmt.where(LogAuditoria.entidad_id == entidad_id)
    if desde:
        stmt = stmt.where(LogAuditoria.created_at >= datetime.combine(desde, time.min, tzinfo=UTC))
    if hasta:
        stmt = stmt.where(LogAuditoria.created_at < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=UTC))
    res = paginate(db, stmt, params, lambda r: {
        "id": r.id, "created_at": r.created_at, "actor_id": r.actor_id, "actor_rol": r.actor_rol, "accion": r.accion,
        "entidad": r.entidad, "entidad_id": r.entidad_id, "estudiante_id": r.estudiante_id, "ip": r.ip,
        "request_id": r.request_id, "detalle": _limpiar(r.detalle),
    })
    audit.log(db, admin, "ACCESO_AUDITORIA", "log_auditoria", None,
              {"filtros": {k: v for k, v in {"actor_id": actor_id, "accion": accion, "entidad": entidad}.items() if v}},
              request=request, commit=True)
    return res


@router.get("/auditoria/acciones")
def auditoria_acciones(db: Session = Depends(get_db), _: Usuario = ADMIN):
    return {"items": sorted(db.scalars(select(LogAuditoria.accion).distinct()))}


# ----------------------------------------------------------------------------- jobs diarios
@router.post("/jobs/run-daily")
def run_daily(
    request: Request, hoy: date | None = Query(None, description="Fecha a simular (AAAA-MM-DD); por defecto, hoy"),
    x_jobs_secret: str | None = Header(None, alias="X-Jobs-Secret"),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db),
):
    """Ejecuta los jobs diarios. Autorización: header `X-Jobs-Secret` (cron externo) o un ADMIN autenticado."""
    secreto = get_settings().jobs_secret
    if x_jobs_secret is not None:
        if not secreto or not hmac.compare_digest(x_jobs_secret.encode(), secreto.encode()):
            raise Unauthorized("El secreto de jobs no es válido.", "JOBS_SECRET_INVALIDO")
        origen = "secreto"
    elif creds is not None:
        user = get_current_user(request, creds, db)
        if str(user.rol) != Rol.ADMIN:
            raise Forbidden("Solo el administrador puede ejecutar los jobs.", "ROL_NO_PERMITIDO")
        origen = f"admin:{user.id}"
    else:
        raise Unauthorized("Falta el secreto de jobs (X-Jobs-Secret) o iniciar sesión como administrador.", "JOBS_SECRET_REQUERIDO")
    dia = hoy or date.today()
    resultados = jobs.run_daily_jobs(db, dia)
    return {"ejecutado_at": utcnow(), "hoy": dia, "origen": origen, "resultados": resultados,
            "errores": sum(1 for r in resultados.values() if "error" in r)}


# ----------------------------------------------------------------------------- cola de correo
@router.post("/email-outbox/reintentar")
def reintentar_outbox(request: Request, body: OutboxRetry | None = None, db: Session = Depends(get_db),
                      admin: Usuario = ADMIN):
    """Devuelve a PENDIENTE los correos con error (o los `ids` indicados) y reintenta el envío."""
    body = body or OutboxRetry()
    stmt = select(EmailOutbox).order_by(EmailOutbox.id).limit(body.limite)
    if body.ids:
        stmt = stmt.where(EmailOutbox.id.in_(body.ids), EmailOutbox.estado.in_([EstadoEmail.ERROR, EstadoEmail.OMITIDO, EstadoEmail.PENDIENTE]))
    else:
        stmt = stmt.where(EmailOutbox.estado == EstadoEmail.ERROR)
    filas = list(db.scalars(stmt))
    for r in filas:
        r.estado, r.intentos, r.ultimo_error = EstadoEmail.PENDIENTE, 0, None
    db.flush()
    smtp = get_settings().smtp_configured
    for r in filas:
        email_service.deliver(r)
    estados = [str(r.estado) for r in filas]
    audit.log(db, admin, "EMAIL_OUTBOX_REINTENTADO", "email_outbox", None, {"filas": len(filas)}, request=request)
    db.commit()
    return {
        "reintentados": len(filas), "enviados": estados.count("ENVIADO"), "con_error": estados.count("ERROR") + estados.count("PENDIENTE"),
        "omitidos": estados.count("OMITIDO"), "smtp_configurado": smtp,
        "detail": "Reintento terminado." if smtp else "No hay servidor de correo (SMTP) configurado: los mensajes quedan registrados en la cola.",
    }


# ----------------------------------------------------------------------------- AQ-10
def _aq10_out(db: Session) -> dict:
    cfg = aq10_config.get_active_config(db)
    return {**cfg.to_dict(), "versiones": aq10_config.list_versions(db)}


@router.get("/aq10")
def ver_aq10(db: Session = Depends(get_db), _: Usuario = ADMIN):
    return _aq10_out(db)


@router.put("/aq10")
def guardar_aq10(body: Aq10Update, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    """Crea una NUEVA versión activa del AQ-10 (la anterior queda inactiva; las respuestas históricas no se tocan)."""
    aq10_config.save_new_version(
        db, admin, items=[i.model_dump() for i in body.items], opciones=[o.model_dump() for o in body.opciones],
        instrucciones=body.instrucciones, nombre=body.nombre, idioma=body.idioma, fuente=body.fuente,
        revision_linguistica_pendiente=body.revision_linguistica_pendiente, punto_corte=body.punto_corte, request=request,
    )
    db.commit()
    return _aq10_out(db)


@router.put("/aq10/punto-corte")
def punto_corte(body: PuntoCorteBody, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    aq10_config.set_punto_corte(db, admin, body.punto_corte, request=request)
    db.commit()
    return {"punto_corte": body.punto_corte, "detail": "Punto de corte actualizado. Las aplicaciones anteriores conservan el corte con el que se calcularon."}


@router.post("/aq10/inicializar")
def inicializar_aq10(request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    """Carga la versión inicial del instrumento AQ-10 en español si aún no está configurado."""
    row = aq10_config.get_active_row(db)
    if row is None:
        from app.data import aq10 as aq10_data
        from app.models.consentimiento import CuestionarioAQ10
        nueva = CuestionarioAQ10(
            nombre="AQ-10 Adultos (Allison et al., 2012) — español",
            version="1.0",
            idioma="es-CO",
            fuente=aq10_data.FUENTE,
            items=aq10_data.items_json(),
            opciones=aq10_data.opciones_json(),
            punto_corte=aq10_data.PUNTO_CORTE,
            revision_linguistica_pendiente=True,
            activo=True,
        )
        db.add(nueva)
        db.flush()
        audit.log(db, admin, "AQ10_INICIALIZADO", "cuestionario_aq10", nueva.id, request=request)
        db.commit()
    return _aq10_out(db)


# ----------------------------------------------------------------------------- Vía 3: CSV / Excel
@router.get("/estudiantes/plantilla-csv")
def plantilla(_: Usuario = ADMIN):
    return Response("﻿" + csv_import.plantilla_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_estudiantes.csv"'})


@router.get("/estudiantes/plantilla-xlsx")
def plantilla_xlsx_descarga(_: Usuario = ADMIN):
    return Response(
        csv_import.plantilla_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_estudiantes.xlsx"'},
    )


@router.post("/estudiantes/importar-csv")
@router.post("/estudiantes/importar")
async def importar_csv(
    request: Request, archivo: UploadFile = File(...), dry_run: bool = Query(True), omitir_errores: bool = Query(False),
    db: Session = Depends(get_db), admin: Usuario = ADMIN,
):
    """Vía 3. `dry_run=true` (por defecto) valida y devuelve errores por fila sin escribir; con `false` importa."""
    contenido = await archivo.read()
    res = csv_import.import_students(db, admin, contenido, dry_run=dry_run, omitir_errores=omitir_errores,
                                     nombre_archivo=archivo.filename, request=request)
    db.commit()
    return res
