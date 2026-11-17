"""Derechos ARCO (RNF-07, Ley 1581 de 2012): solicitudes con plazos, exportación de datos propios y recolección de las
filas de un estudiante (usada también por la revocación del consentimiento para archivar).

Plazos (art. 14 de la Ley 1581): consultas (ACCESO) 10 días hábiles, prorrogables 5; reclamos (RECTIFICACION,
CANCELACION, OPOSICION) 15 días hábiles, prorrogables 8. Se cuentan lunes a viernes sin descontar festivos.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.base import Base, utcnow
from app.models.sistema import LogAuditoria
from app.models.slice_b import EstadoArco, SolicitudArco, TipoArco
from app.models.usuarios import Estudiante, Usuario
from app.services.b_common import AccionB, add_business_days, row_to_dict
from app.services.notifications import Evento, get_notification_user_ids, notify

PLAZO_DIAS = {TipoArco.ACCESO: 10, TipoArco.RECTIFICACION: 15, TipoArco.CANCELACION: 15, TipoArco.OPOSICION: 15}
PRORROGA_DIAS = {TipoArco.ACCESO: 5, TipoArco.RECTIFICACION: 8, TipoArco.CANCELACION: 8, TipoArco.OPOSICION: 8}
TIPO_TRAMITE = {TipoArco.ACCESO: "CONSULTA", TipoArco.RECTIFICACION: "RECLAMO", TipoArco.CANCELACION: "RECLAMO",
                TipoArco.OPOSICION: "RECLAMO"}

#: Tablas que NO se archivan ni se exportan como «datos del estudiante en el STI».
#: matricula / registro_inasistencia son registros académicos institucionales (base legal distinta del consentimiento F0);
#: caso_cbr es anónimo; el resto son infraestructura o evidencia legal que debe conservarse.
EXCLUIR_TABLAS = {
    "estudiante", "usuario", "consentimiento", "consentimiento_detalle", "solicitud_arco", "log_auditoria",
    "caso_cbr", "matricula", "registro_inasistencia", "refresh_token", "notificacion", "email_outbox",
    "preferencia_sensorial_ui", "parametro_sistema", "programa_academico", "estado_plan",
    "estrategia_dua_catalogo", "cuestionario_aq10", "asignatura", "asignacion_docente", "calendario_academico",
}


def radicado(s: SolicitudArco) -> str:
    return f"ARCO-{s.created_at.year}-{s.id:06d}"


# ============================================================================ filas del estudiante
def _models_by_table() -> dict[str, type]:
    return {m.local_table.name: m.class_ for m in Base.registry.mappers if hasattr(m.class_, "deleted_at")}


def collect_student_rows(db: Session, est: Estudiante) -> dict[str, list[Any]]:
    """Todas las filas (no eliminadas) que cuelgan del estudiante: tablas con `estudiante_id` y, de forma transitiva,
    las tablas hijas (FK hacia filas ya recolectadas)."""
    models = _models_by_table()
    rows: dict[str, dict[int, Any]] = {}
    for tname, model in models.items():
        if tname in EXCLUIR_TABLAS or "estudiante_id" not in model.__table__.c:
            continue
        found = db.scalars(select(model).where(model.__table__.c.estudiante_id == est.id)).all()
        if found:
            rows[tname] = {r.id: r for r in found}
    changed = True
    while changed:
        changed = False
        for tname, model in models.items():
            if tname in EXCLUIR_TABLAS:
                continue
            for fk in model.__table__.foreign_keys:
                parent = fk.column.table.name
                if parent not in rows or fk.column.name != "id":
                    continue
                col = fk.parent
                found = db.scalars(select(model).where(col.in_(list(rows[parent])))).all()
                new = [r for r in found if r.id not in rows.get(tname, {})]
                if new:
                    rows.setdefault(tname, {}).update({r.id: r for r in new})
                    changed = True
    return {t: list(d.values()) for t, d in rows.items()}


def export_student_data(db: Session, est: Estudiante, user: Usuario) -> dict[str, Any]:
    """Volcado JSON de los datos propios, DESCIFRADOS (derecho de acceso)."""
    from app.models.consentimiento import Consentimiento
    from app.models.slice_b import ConsentimientoDetalle

    tablas: dict[str, list[dict]] = {}
    for tname, objs in sorted(collect_student_rows(db, est).items()):
        tablas[tname] = [row_to_dict(o) for o in sorted(objs, key=lambda o: o.id)]
    consents = db.scalars(select(Consentimiento).where(Consentimiento.estudiante_id == est.id)
                          .execution_options(include_deleted=True)).all()
    detalles = {d.consentimiento_id: d for d in db.scalars(select(ConsentimientoDetalle)).all()}
    solicitudes = db.scalars(select(SolicitudArco).where(SolicitudArco.estudiante_id == est.id)).all()
    accesos = db.scalars(
        select(LogAuditoria).where(LogAuditoria.estudiante_id == est.id).order_by(LogAuditoria.id.desc()).limit(500)
    ).all()
    return {
        "generado_at": utcnow().isoformat(),
        "aviso": "Estos son los datos que el STI guarda sobre usted. Los datos sensibles aparecen descifrados.",
        "cuenta": {
            "email": user.email, "nombre_completo": user.nombre_completo, "telefono": user.telefono,
            "numero_documento": user.numero_documento, "estado": str(user.estado), "creada_at": user.created_at.isoformat(),
        },
        "estudiante": row_to_dict(est),
        "consentimientos": [
            {**row_to_dict(c), "detalle": row_to_dict(detalles[c.id]) if c.id in detalles else None} for c in consents
        ],
        "solicitudes_arco": [row_to_dict(s) | {"radicado": radicado(s)} for s in solicitudes],
        "datos": tablas,
        "accesos_a_mis_datos": [
            {"fecha": a.created_at.isoformat(), "accion": a.accion, "rol": a.actor_rol, "entidad": a.entidad}
            for a in accesos
        ],
    }


# ============================================================================ solicitudes
def create_request(db: Session, est: Estudiante, user: Usuario, tipo: TipoArco, descripcion: str) -> SolicitudArco:
    descripcion = (descripcion or "").strip()
    if len(descripcion) < 10:
        raise Unprocessable("Cuéntenos con un poco más de detalle qué necesita (mínimo 10 caracteres).", "DESCRIPCION_MUY_CORTA")
    s = SolicitudArco(
        estudiante_id=est.id, solicitante_id=user.id, tipo=tipo, descripcion=descripcion,
        fecha_limite=add_business_days(date.today(), PLAZO_DIAS[tipo]),
    )
    db.add(s)
    db.flush()
    audit.log(db, user, AccionB.ARCO_SOLICITUD, "solicitud_arco", s.id, {"tipo": str(tipo), "radicado": radicado(s)},
              estudiante_id=est.id)
    dest = [est.bienestar_asignado_id] if est.bienestar_asignado_id else get_notification_user_ids(db, "BIENESTAR")
    notify(db, Evento.ARCO_SOLICITUD_NUEVA, dest,
           {"tipo": str(tipo).lower(), "fecha_limite": s.fecha_limite.isoformat(), "enlace": f"/bienestar/arco/{s.id}"})
    return s


def get_request(db: Session, solicitud_id: int) -> SolicitudArco:
    s = db.get(SolicitudArco, solicitud_id)
    if s is None:
        raise NotFound("No encontramos la solicitud indicada.", "ARCO_NO_ENCONTRADA")
    return s


def manage_request(db: Session, s: SolicitudArco, actor: Usuario, *, estado: EstadoArco | None, respuesta: str | None) -> SolicitudArco:
    if s.estado in (EstadoArco.RESUELTA, EstadoArco.RECHAZADA):
        raise Conflict("Esta solicitud ya fue cerrada.", "ARCO_CERRADA")
    if estado is None or estado == EstadoArco.RECIBIDA:
        raise Unprocessable("Indique el nuevo estado: EN_TRAMITE, RESUELTA o RECHAZADA.", "ESTADO_INVALIDO")
    if estado in (EstadoArco.RESUELTA, EstadoArco.RECHAZADA) and not (respuesta or "").strip():
        raise Unprocessable(
            "Para cerrar la solicitud escriba la respuesta para el estudiante (si la rechaza, explique el motivo).",
            "RESPUESTA_REQUERIDA",
        )
    s.estado = estado
    if respuesta is not None and respuesta.strip():
        s.respuesta = respuesta.strip()
    s.atendida_por_id = actor.id
    s.atendida_at = utcnow()
    audit.log(db, actor, AccionB.ARCO_GESTION, "solicitud_arco", s.id, {"estado": str(estado), "radicado": radicado(s)},
              estudiante_id=s.estudiante_id)
    if estado in (EstadoArco.RESUELTA, EstadoArco.RECHAZADA):
        est = db.get(Estudiante, s.estudiante_id)
        notify(db, Evento.ARCO_SOLICITUD_RESUELTA, [est.usuario_id],
               {"tipo": str(s.tipo).lower(), "estado": str(estado).lower(), "enlace": f"/estudiante/derechos/{s.id}"})
    return s


def extend_deadline(db: Session, s: SolicitudArco, actor: Usuario, motivo: str) -> SolicitudArco:
    if s.estado in (EstadoArco.RESUELTA, EstadoArco.RECHAZADA):
        raise Conflict("Esta solicitud ya fue cerrada.", "ARCO_CERRADA")
    if s.prorrogada:
        raise Conflict("La ley permite una sola prórroga y ya fue usada.", "ARCO_YA_PRORROGADA")
    if len((motivo or "").strip()) < 10:
        raise Unprocessable("Explique el motivo de la prórroga (mínimo 10 caracteres): se le informa al estudiante.", "MOTIVO_REQUERIDO")
    s.fecha_limite = add_business_days(s.fecha_limite, PRORROGA_DIAS[s.tipo])
    s.prorrogada = True
    s.motivo_prorroga = motivo.strip()[:500]
    audit.log(db, actor, AccionB.ARCO_GESTION, "solicitud_arco", s.id, {"prorroga": True, "nueva_fecha": s.fecha_limite.isoformat()},
              estudiante_id=s.estudiante_id)
    return s


def serialize(s: SolicitudArco, *, para_estudiante: bool = False) -> dict[str, Any]:
    hoy = date.today()
    abierta = s.estado in (EstadoArco.RECIBIDA, EstadoArco.EN_TRAMITE)
    d = {
        "id": s.id, "radicado": radicado(s), "estudiante_id": s.estudiante_id, "tipo": str(s.tipo),
        "tramite": TIPO_TRAMITE[s.tipo], "descripcion": s.descripcion, "estado": str(s.estado),
        "fecha_radicacion": s.created_at.date().isoformat(), "fecha_limite": s.fecha_limite.isoformat(),
        "prorrogada": s.prorrogada, "motivo_prorroga": s.motivo_prorroga,
        "dias_para_vencer": (s.fecha_limite - hoy).days if abierta else None,
        "vencida": bool(abierta and s.fecha_limite < hoy),
        "respuesta": s.respuesta, "atendida_at": s.atendida_at.isoformat() if s.atendida_at else None,
    }
    if not para_estudiante:
        d["solicitante_id"] = s.solicitante_id
        d["atendida_por_id"] = s.atendida_por_id
    return d
