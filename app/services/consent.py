"""F0: firma, estado y revocación del consentimiento informado (RF-05/06/07, Ley 1581/2012, HU-05/HU-18)."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.audit import client_ip
from app.core.errors import Conflict, Forbidden, Unprocessable
from app.core.security import revoke_all_user_tokens
from app.data import f0_texto
from app.models.base import utcnow
from app.models.consentimiento import AutorizacionFamiliar, Consentimiento
from app.models.dua import CasoCbr
from app.models.enums import EstadoAutorizacionFamiliar, EstadoConsentimiento, EstadoUsuario, Rol
from app.models.slice_b import ConsentimientoDetalle, ModalidadFirma
from app.models.usuarios import Estudiante, Usuario
from app.services.arco import collect_student_rows
from app.services.b_common import name_matches
from app.services.notifications import Evento, get_notification_user_ids, notify


def latest_consent(db: Session, estudiante_id: int) -> Consentimiento | None:
    return db.scalar(
        select(Consentimiento).where(Consentimiento.estudiante_id == estudiante_id).order_by(Consentimiento.id.desc())
    )


def detail_of(db: Session, c: Consentimiento | None) -> ConsentimientoDetalle | None:
    if c is None:
        return None
    return db.scalar(select(ConsentimientoDetalle).where(ConsentimientoDetalle.consentimiento_id == c.id))


def state(db: Session, est: Estudiante, *, staff: bool = False) -> dict[str, Any]:
    c = latest_consent(db, est.id)
    d = detail_of(db, c)
    out: dict[str, Any] = {
        "estudiante_id": est.id,
        "estado": "PENDIENTE" if c is None else str(c.estado),
        "firmado": bool(c and c.estado == EstadoConsentimiento.FIRMADO),
        "version_vigente": f0_texto.VERSION,
        "version_firmada": c.version_texto if c else None,
        "texto_desactualizado": bool(c and c.estado == EstadoConsentimiento.FIRMADO and c.version_texto != f0_texto.VERSION),
        "firmado_at": c.firmado_at.isoformat() if c else None,
        "nombre_firmante": d.nombre_firmante if d else None,
        "modalidad": str(d.modalidad) if d else None,
        "acepta_tratamiento_general": bool(c.acepta_politica_privacidad) if c else None,
        "acepta_datos_sensibles_salud": bool(c.acepta_tratamiento_datos_sensibles) if c else None,
        "acepta_compartir_ajustes_docentes": bool(d.acepta_compartir_ajustes_docentes) if d else None,
        "copia_enviada_at": d.copia_enviada_at.isoformat() if d and d.copia_enviada_at else None,
        "revocado_at": c.revocado_at.isoformat() if c and c.revocado_at else None,
        "firma_hash": c.firma_hash if c else None,
        "texto_hash": c.texto_hash if c else None,
    }
    if staff:
        out["asistido_por_id"] = d.asistido_por_id if d else None
        out["motivo_revocacion"] = c.motivo_revocacion if c else None
    return out


def sign(
    db: Session, est: Estudiante, actor: Usuario, *, version_texto: str, texto_hash: str, nombre_firmante: str,
    acepta_tratamiento_general: bool, acepta_datos_sensibles_salud: bool, acepta_compartir_ajustes_docentes: bool,
    request: Request | None = None,
) -> Consentimiento:
    est_user = db.get(Usuario, est.usuario_id)
    prev = latest_consent(db, est.id)
    if prev is not None and prev.estado == EstadoConsentimiento.FIRMADO:
        raise Conflict("Este consentimiento ya fue firmado. Si quiere retirarlo, use «Retirar mi consentimiento».", "CONSENTIMIENTO_YA_FIRMADO")
    if prev is not None and prev.estado == EstadoConsentimiento.REVOCADO:
        raise Conflict(
            "El consentimiento fue retirado y la cuenta está inactiva. Para volver a participar, Bienestar debe solicitar "
            "la reactivación de la cuenta al administrador.", "CONSENTIMIENTO_REVOCADO",
        )
    if str(est_user.estado) == EstadoUsuario.INACTIVO:
        raise Forbidden("La cuenta está inactiva.", "CUENTA_INACTIVA")
    if version_texto != f0_texto.VERSION or texto_hash != f0_texto.texto_hash():
        raise Conflict("El texto del consentimiento cambió. Vuelva a leerlo antes de firmar.", "TEXTO_DESACTUALIZADO",
                       extra={"version_vigente": f0_texto.VERSION})
    if not (acepta_tratamiento_general and acepta_datos_sensibles_salud):
        raise Unprocessable(
            "Para firmar debe aceptar el tratamiento de datos personales y la autorización de datos sensibles de salud. "
            "Si no está de acuerdo, no firme: no habrá ninguna consecuencia académica.", "ACEPTACION_REQUERIDA",
        )
    if not name_matches(nombre_firmante, est_user.nombre_completo):
        raise Unprocessable(
            "El nombre escrito no coincide con el de su cuenta. Escriba su nombre y apellido tal como aparece en su cuenta.",
            "NOMBRE_NO_COINCIDE",
        )
    asistida = str(actor.rol) == Rol.BIENESTAR
    ahora = utcnow()
    firma = hashlib.sha256(
        f"{est.id}|{f0_texto.VERSION}|{f0_texto.texto_hash()}|{ahora.isoformat()}|{' '.join(sorted(set(nombre_firmante.lower().split())))}".encode()
    ).hexdigest()
    ua = request.headers.get("user-agent", "")[:255] if request is not None else None
    c = Consentimiento(
        estudiante_id=est.id, version_texto=f0_texto.VERSION, texto_hash=f0_texto.texto_hash(),
        acepta_tratamiento_datos_sensibles=True, acepta_politica_privacidad=True, firmado_at=ahora, firma_hash=firma,
        firmado_por_id=est_user.id, ip=client_ip(request), user_agent=ua or None, estado=EstadoConsentimiento.FIRMADO,
    )
    db.add(c)
    db.flush()
    d = ConsentimientoDetalle(
        consentimiento_id=c.id, nombre_firmante=nombre_firmante.strip(),
        modalidad=ModalidadFirma.ASISTIDA_BIENESTAR if asistida else ModalidadFirma.AUTONOMA,
        asistido_por_id=actor.id if asistida else None,
        acepta_compartir_ajustes_docentes=acepta_compartir_ajustes_docentes,
    )
    db.add(d)
    if str(est_user.estado) == EstadoUsuario.PENDIENTE_CONSENTIMIENTO:
        est_user.estado = EstadoUsuario.ACTIVO
    audit.log(db, actor, audit.Accion.CONSENTIMIENTO_FIRMADO, "consentimiento", c.id,
              {"version": c.version_texto, "modalidad": str(d.modalidad), "texto_hash": c.texto_hash,
               "acepta_compartir_ajustes_docentes": acepta_compartir_ajustes_docentes},
              request=request, estudiante_id=est.id)
    notify(db, Evento.CONSENTIMIENTO_COPIA, [est_user], {
        "version_texto": c.version_texto, "firmado_at": ahora.isoformat(timespec="seconds"), "texto_hash": c.texto_hash,
        "texto_f0": f0_texto.texto_plano_correo(),
    })
    d.copia_enviada_at = utcnow()
    db.flush()
    return c


def archive_student_data(db: Session, est: Estudiante, actor: Usuario, reason: str) -> dict[str, int]:
    """Soft delete de todos los datos del estudiante en el STI (ver `arco.EXCLUIR_TABLAS` para lo que se conserva)."""
    resumen: dict[str, int] = {}
    rows = collect_student_rows(db, est)
    for tname, objs in rows.items():
        for o in objs:
            o.soft_delete(actor.id, reason)
        resumen[tname] = len(objs)
    # casos CBR: anónimos; se corta el vínculo con el plan para que no permita reidentificar.
    plan_ids = [o.id for o in rows.get("plan_maar_tea", [])]
    if plan_ids:
        db.execute(update(CasoCbr).where(CasoCbr.plan_id.in_(plan_ids)).values(plan_id=None))
    return resumen


def revoke(db: Session, est: Estudiante, actor: Usuario, *, motivo: str | None, request: Request | None = None) -> dict[str, Any]:
    c = latest_consent(db, est.id)
    if c is None or c.estado != EstadoConsentimiento.FIRMADO:
        raise Conflict("No hay un consentimiento firmado para retirar.", "SIN_CONSENTIMIENTO_VIGENTE")
    ahora = utcnow()
    c.estado = EstadoConsentimiento.REVOCADO
    c.revocado_at = ahora
    c.motivo_revocacion = (motivo or "").strip() or None
    user = db.get(Usuario, est.usuario_id)
    user.estado = EstadoUsuario.INACTIVO
    revoke_all_user_tokens(db, user.id)
    for a in db.scalars(select(AutorizacionFamiliar).where(AutorizacionFamiliar.estudiante_id == est.id)):
        a.estado = EstadoAutorizacionFamiliar.REVOCADA
        a.revocada_at = ahora
        a.motivo_revocacion = "Revocación del consentimiento F0"
    resumen = archive_student_data(db, est, actor, "REVOCACION_CONSENTIMIENTO")
    audit.log(db, actor, audit.Accion.CONSENTIMIENTO_REVOCADO, "consentimiento", c.id,
              {"archivado": resumen, "con_motivo": bool(c.motivo_revocacion)}, request=request, estudiante_id=est.id)
    dest = [est.bienestar_asignado_id] if est.bienestar_asignado_id else get_notification_user_ids(db, "BIENESTAR")
    notify(db, Evento.CONSENTIMIENTO_REVOCADO, dest, {"enlace": f"/bienestar/estudiantes/{est.id}"})
    db.flush()
    return {"estado": "REVOCADO", "revocado_at": ahora.isoformat(), "datos_archivados": resumen}
