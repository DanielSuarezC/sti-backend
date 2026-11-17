"""Firma digital del Plan MAAR-TEA (RF-24): contenido canónico, hash SHA-256, versiones congeladas y verificación.

Modelo:
* El plan "vivo" son las tablas (plan, estrategias, ajustes). `contenido_canonico` los serializa de forma estable
  (sin estado de workflow, aceptaciones, semáforo ni comentarios) y `hash_contenido` calcula su SHA-256.
* Al pasar a PENDIENTE_FIRMAS (validación del Coordinador) se CONGELA la versión: `PLAN_VERSION` guarda el snapshot y su
  hash. Cada firma (`FIRMA_PLAN`, registro de solo anexo) guarda ese hash + sello de tiempo del servidor + IP/UA.
* Cualquier modificación posterior abre una versión nueva (`plan_workflow.preparar_edicion`) y marca como INVALIDADA la
  firma de la versión anterior; la firma anterior nunca se borra.
* `verificar` recalcula el hash del contenido y lo compara con el firmado.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, Forbidden
from app.models.base import utcnow
from app.models.enums import EstadoFirma, EstadoPlanEnum, Rol, RolFirmante
from app.models.plan import AjusteRazonable, EstrategiaDua, FirmaPlan, PlanMaarTea, PlanVersion
from app.models.usuarios import Usuario
from app.services import plan_categorias as cats
from app.services import plan_common as common
from app.services.notifications import Evento
from app.services.params import get_param
from app.services.plan_states import assert_transition

ROLES_FIRMANTES = (RolFirmante.ESTUDIANTE, RolFirmante.BIENESTAR, RolFirmante.COORDINADOR)
_ROL_USUARIO_A_FIRMANTE = {Rol.ESTUDIANTE: RolFirmante.ESTUDIANTE, Rol.BIENESTAR: RolFirmante.BIENESTAR,
                           Rol.COORDINADOR: RolFirmante.COORDINADOR}


# ----------------------------------------------------------------------------- contenido canónico y hash
def _v(valor: Any) -> Any:
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def contenido_canonico(db: Session, plan: PlanMaarTea) -> dict:
    """Contenido firmable del plan en su versión vigente (estable: ordenado por id, sin metadatos de workflow)."""
    db.flush()
    ajustes = []
    for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id)):
        ajustes.append({
            "id": a.id, "nombre_ajuste": a.nombre_ajuste, "descripcion_ajuste": a.descripcion_ajuste,
            "justificacion": a.justificacion, "tipo_ajuste": _v(a.tipo_ajuste), "detalle": cats.leer_detalle(db, a),
            "barrera_asociada_id": a.barrera_asociada_id, "fortaleza_apoyo_id": a.fortaleza_apoyo_id,
            "responsable_id": a.responsable_id, "asignatura_id": a.asignatura_id,
            "asignatura_si_aplica": a.asignatura_si_aplica, "actividad_si_aplica": a.actividad_si_aplica,
            "especificidad": _v(a.especificidad), "recurso": a.recurso, "frecuencia": a.frecuencia,
            "indicador_efectividad": a.indicador_efectividad, "fecha_inicio": _v(a.fecha_inicio),
            "fecha_fin_prevista": _v(a.fecha_fin_prevista), "permanencia_indefinida": a.permanencia_indefinida,
        })
    estrategias = []
    for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id).order_by(EstrategiaDua.id)):
        estrategias.append({
            "id": e.id, "nombre_estrategia": e.nombre_estrategia, "descripcion": e.descripcion,
            "dimension_dua": _v(e.dimension_dua), "responsable_implementacion_id": e.responsable_implementacion_id,
            "alcance": e.alcance, "fecha_inicio_implementacion": _v(e.fecha_inicio_implementacion),
            "estrategia_catalogo_id": e.estrategia_catalogo_id, "asignatura_id": e.asignatura_id,
            "escenario": _v(e.escenario), "barrera_id": e.barrera_id, "fortaleza_id": e.fortaleza_id,
        })
    return {
        "plan": {
            "id": plan.id, "estudiante_id": plan.estudiante_id, "semestre_academico": plan.semestre_academico,
            "version": plan.version, "vigencia_inicio": _v(plan.vigencia_inicio), "vigencia_fin": _v(plan.vigencia_fin),
            "resumen_ejecutivo": plan.resumen_ejecutivo, "justificacion_apoyos": plan.justificacion_apoyos,
            "participacion_familia": plan.participacion_familia,
        },
        "estrategias_dua": estrategias,
        "ajustes": ajustes,
    }


def canonical_json(contenido: dict) -> str:
    return json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def hash_contenido(contenido: dict) -> str:
    return hashlib.sha256(canonical_json(contenido).encode("utf-8")).hexdigest()


def hash_corto(h: str | None) -> str | None:
    return h[:12] if h else None


def calcular_firma_hash(hash_documento: str, plan_id: int, version: int, rol: str, firmante_id: int,
                        firmado_at: datetime) -> str:
    ts = firmado_at.astimezone(UTC).isoformat(timespec="microseconds")
    return hashlib.sha256(f"{hash_documento}|{plan_id}|{version}|{rol}|{firmante_id}|{ts}".encode()).hexdigest()


# ----------------------------------------------------------------------------- versiones congeladas
def version_activa(db: Session, plan_id: int, version: int) -> PlanVersion | None:
    db.flush()
    return db.scalar(select(PlanVersion).where(PlanVersion.plan_id == plan_id, PlanVersion.version == version))


def _motivo_version(plan: PlanMaarTea) -> str:
    for e in reversed(plan.participacion_log or []):
        if e.get("accion") == "NUEVA_VERSION" and (e.get("detalle") or {}).get("version") == plan.version:
            return (e["detalle"].get("motivo") or "Modificación del plan")
    return "Versión inicial" if plan.version == 1 else "Modificación del plan"


def congelar_version(db: Session, plan: PlanMaarTea, actor: Usuario | None) -> PlanVersion:
    """Guarda el snapshot inmutable de la versión vigente (reemplaza —con soft delete— un snapshot previo sin firmas)."""
    contenido = contenido_canonico(db, plan)
    previa = version_activa(db, plan.id, plan.version)
    if previa is not None:
        previa.soft_delete(actor.id if actor else None, "Snapshot reemplazado antes de firmas")
        db.flush()
    pv = PlanVersion(
        plan_id=plan.id, version=plan.version, estado_plan=str(plan.estado), snapshot=contenido,
        hash_snapshot=hash_contenido(contenido), motivo_cambio=_motivo_version(plan),
        creado_por_id=actor.id if actor else None,
    )
    db.add(pv)
    db.flush()
    return pv


def firmas_de(db: Session, plan_id: int, version: int | None = None, *, solo_vigentes: bool = False) -> list[FirmaPlan]:
    db.flush()
    stmt = select(FirmaPlan).where(FirmaPlan.plan_id == plan_id).order_by(FirmaPlan.version, FirmaPlan.firmado_at, FirmaPlan.id)
    if version is not None:
        stmt = stmt.where(FirmaPlan.version == version)
    if solo_vigentes:
        stmt = stmt.where(FirmaPlan.estado == EstadoFirma.FIRMADA)
    return list(db.scalars(stmt))


def invalidar_firmas(db: Session, plan: PlanMaarTea, actor: Usuario | None, motivo: str, request: Request | None = None) -> int:
    """Marca INVALIDADA toda firma FIRMADA de la versión vigente (la fila se conserva: es evidencia)."""
    n = 0
    for f in firmas_de(db, plan.id, plan.version, solo_vigentes=True):
        f.estado = EstadoFirma.INVALIDADA
        n += 1
    if n:
        audit.log(db, actor, common.A_FIRMAS_INVALIDADAS, "plan_maar_tea", plan.id,
                  {"version": plan.version, "firmas": n, "motivo": motivo}, request=request,
                  estudiante_id=plan.estudiante_id)
    return n


# ----------------------------------------------------------------------------- firma
def rol_firmante_de(user: Usuario) -> RolFirmante:
    rol = _ROL_USUARIO_A_FIRMANTE.get(Rol(str(user.rol)))
    if rol is None:
        raise Forbidden("Solo el estudiante, Bienestar y el Coordinador firman el plan.", "ROL_NO_FIRMA")
    return rol


def orden_firmas(db: Session) -> list[str]:
    """Orden configurable (parámetro `plan_firmas_orden`; por defecto estudiante, Bienestar, coordinador)."""
    raw = get_param(db, "plan_firmas_orden", [r.value for r in ROLES_FIRMANTES])
    orden = [str(r).upper() for r in raw if str(r).upper() in {x.value for x in ROLES_FIRMANTES}]
    return orden or [r.value for r in ROLES_FIRMANTES]


def estado_firmas(db: Session, plan: PlanMaarTea) -> dict:
    vigentes = {str(f.rol_firmante) for f in firmas_de(db, plan.id, plan.version, solo_vigentes=True)}
    orden = orden_firmas(db)
    return {
        "version": plan.version, "orden": orden, "firmadas": [r for r in orden if r in vigentes],
        "pendientes": [r for r in orden if r not in vigentes], "completas": all(r in vigentes for r in orden),
    }


def firmar(db: Session, plan: PlanMaarTea, user: Usuario, request: Request | None = None) -> dict:
    """Registra la firma del usuario sobre la versión vigente. Con las 3 firmas el plan pasa a APROBADO."""
    if plan.estado != EstadoPlanEnum.PENDIENTE_FIRMAS:
        raise Conflict(
            "El plan solo se puede firmar cuando el Coordinador ya lo validó y está en PENDIENTE_FIRMAS "
            f"(estado actual: {plan.estado}).", "PLAN_NO_ESTA_EN_FIRMAS")
    rol = rol_firmante_de(user)
    estado = estado_firmas(db, plan)
    if rol.value in estado["firmadas"]:
        raise Conflict("Usted ya firmó esta versión del plan.", "FIRMA_YA_REGISTRADA")
    if get_param(db, "plan_firmas_orden_estricto", False):
        previos = estado["orden"][: estado["orden"].index(rol.value)]
        faltan = [r for r in previos if r not in estado["firmadas"]]
        if faltan:
            raise Conflict(f"Antes de su firma deben firmar: {', '.join(faltan)}.", "FIRMA_FUERA_DE_ORDEN",
                           extra={"faltan": faltan})
    contenido = contenido_canonico(db, plan)
    h = hash_contenido(contenido)
    snap = version_activa(db, plan.id, plan.version)
    if snap is None or snap.hash_snapshot != h:
        raise Conflict(
            "El contenido del plan cambió después de la validación. Solicite a Bienestar que lo envíe de nuevo a "
            "validación.", "PLAN_MODIFICADO")
    ahora = utcnow()
    firma = FirmaPlan(
        plan_id=plan.id, version=plan.version, rol_firmante=rol, firmante_id=user.id, firmado_at=ahora,
        hash_documento=h, firma_hash=calcular_firma_hash(h, plan.id, plan.version, rol.value, user.id, ahora),
        ip=audit.client_ip(request), user_agent=(request.headers.get("user-agent", "")[:255] or None) if request else None,
        estado=EstadoFirma.FIRMADA,
    )
    db.add(firma)
    db.flush()
    common.log_participacion(plan, user, "FIRMO", "plan", plan.id, {"rol_firmante": rol.value, "version": plan.version})
    audit.log(db, user, audit.Accion.FIRMA_PLAN, "firma_plan", firma.id,
              {"plan_id": plan.id, "version": plan.version, "rol_firmante": rol.value, "hash": hash_corto(h)},
              request=request, estudiante_id=plan.estudiante_id)
    resultado = {"firma": firma, "aprobado": False, "matriz": None}
    if estado_firmas(db, plan)["completas"]:
        resultado["aprobado"] = True
        resultado["matriz"] = _aprobar(db, plan, user, snap, request)
    return resultado


def _aprobar(db: Session, plan: PlanMaarTea, ultimo_firmante: Usuario, snap: PlanVersion, request: Request | None) -> dict:
    assert_transition(plan.estado, EstadoPlanEnum.APROBADO)
    anterior = plan.estado
    plan.estado = EstadoPlanEnum.APROBADO
    plan.fecha_aprobacion = date.today()
    coord_firma = next((f for f in firmas_de(db, plan.id, plan.version, solo_vigentes=True)
                        if f.rol_firmante == RolFirmante.COORDINADOR), None)
    plan.aprobado_por_id = coord_firma.firmante_id if coord_firma else ultimo_firmante.id
    snap.estado_plan = str(plan.estado)
    audit.log(db, ultimo_firmante, common.A_PLAN_ESTADO, "plan_maar_tea", plan.id,
              {"de": str(anterior), "a": str(plan.estado), "version": plan.version}, request=request,
              estudiante_id=plan.estudiante_id)
    db.flush()
    common.notificar_plan(db, Evento.PLAN_FIRMADO_APROBADO, plan, common.actores_del_plan(db, plan))
    # F7 automática al aprobar; si falta el calendario el plan queda aprobado y la matriz pendiente (no se bloquea).
    from app.core.errors import AppError
    from app.services import plan_builder

    try:
        with db.begin_nested():
            apoyos = plan_builder.generar_matriz(db, plan, ultimo_firmante, request=request)
        return {"generada": True, "apoyos": len(apoyos)}
    except AppError as exc:
        return {"generada": False, "motivo": exc.detail, "code": exc.code}


# ----------------------------------------------------------------------------- verificación
def verificar(db: Session, plan: PlanMaarTea) -> dict:
    """Recalcula hashes y compara con lo firmado. Versión vigente: contenido vivo; versiones previas: su snapshot."""
    db.flush()
    versiones = sorted({f.version for f in firmas_de(db, plan.id)} | {plan.version})
    detalle = []
    todo_ok = True
    for v in versiones:
        firmas = firmas_de(db, plan.id, v)
        snap = db.scalar(
            select(PlanVersion).where(PlanVersion.plan_id == plan.id, PlanVersion.version == v)
            .execution_options(include_deleted=True).order_by(PlanVersion.id.desc()))
        if v == plan.version:
            hash_actual = hash_contenido(contenido_canonico(db, plan))
            origen = "contenido_actual"
        elif snap is not None:
            hash_actual = hash_contenido(snap.snapshot)
            origen = "snapshot_congelado"
        else:
            hash_actual, origen = None, "sin_snapshot"
        filas = []
        for f in firmas:
            coincide = hash_actual is not None and f.hash_documento == hash_actual
            firma_ok = f.firma_hash == calcular_firma_hash(f.hash_documento, f.plan_id, f.version, str(f.rol_firmante),
                                                           f.firmante_id, f.firmado_at)
            vigente = f.estado == EstadoFirma.FIRMADA
            valida = bool(vigente and coincide and firma_ok)
            if vigente and not valida:
                todo_ok = False
            filas.append({
                "id": f.id, "rol_firmante": str(f.rol_firmante), "firmante_id": f.firmante_id,
                "firmado_at": f.firmado_at.isoformat(), "estado": str(f.estado), "hash_documento": f.hash_documento,
                "hash_coincide": coincide, "sello_firma_valido": firma_ok, "valida": valida,
            })
        detalle.append({"version": v, "hash_actual": hash_actual, "origen_hash": origen,
                        "hash_snapshot": snap.hash_snapshot if snap else None, "firmas": filas})
    actual = next(d for d in detalle if d["version"] == plan.version)
    vigentes = [f for f in actual["firmas"] if f["estado"] == "FIRMADA"]
    return {
        "plan_id": plan.id, "version": plan.version, "integro": todo_ok,
        "firmas_vigentes": len(vigentes), "firmas_validas": sum(1 for f in vigentes if f["valida"]),
        "completo": len(vigentes) == len(ROLES_FIRMANTES) and all(f["valida"] for f in vigentes),
        "versiones": detalle,
    }
