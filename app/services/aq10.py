"""AQ-10 (RF-09/10/11, HU-06): formulario, puntuación en backend, respuestas cifradas y activación de la ruta MAAR-TEA.

El AQ-10 es TAMIZAJE, no diagnóstico. Este módulo NUNCA se importa desde `ai_gateway` (RF-11).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, Unprocessable
from app.data import aq10 as aq10_data
from app.models.base import utcnow
from app.models.caracterizacion import Caracterizacion
from app.models.consentimiento import CuestionarioAQ10, RespuestaAQ10
from app.models.enums import EstadoCaracterizacion, ModalidadAQ10, Rol
from app.models.usuarios import Estudiante, Usuario
from app.services import params
from app.services.b_common import AccionB
from app.services.notifications import Evento, get_notification_user_ids, notify

try:  # lo crea el slice A
    from app.services.aq10_config import get_active_config as _get_active_config
except Exception:  # pragma: no cover
    _get_active_config = None

DIAS_REAPLICACION_AUTOAPLICADA = 30
MENSAJE_TAMIZAJE = (
    "El AQ-10 es una herramienta de tamizaje: no es un diagnóstico y no dice nada definitivo sobre usted. "
    "Su resultado solo ayuda a decidir si conviene seguir conociendo cómo aprende y qué apoyos le servirían."
)

PROTOCOLO_BIENVENIDA = {
    "titulo": "Antes de empezar",
    "pasos": [
        "Este cuestionario tiene 10 afirmaciones. Elija la opción que mejor lo describe; no hay respuestas buenas ni malas.",
        "Puede tomarse el tiempo que necesite y pausar cuando quiera. Lo que responda se guarda cifrado.",
        "Solo usted y el equipo de Bienestar pueden ver su resultado. Sus docentes nunca lo ven.",
        "Es un tamizaje, no un diagnóstico: no lo etiqueta ni afecta su situación académica.",
        "Si algo le incomoda, puede detenerse y pedir acompañamiento a Bienestar Universitario.",
    ],
    "ayuda": "¿Prefiere hacerlo acompañado? Pida a Bienestar que lo aplique con usted (modalidad asistida).",
}

RECURSOS_BIENESTAR = [
    {"titulo": "Bienestar Universitario", "descripcion": "Orientación y acompañamiento académico y personal. Puede pedir una cita cuando quiera."},
    {"titulo": "Tutorías y apoyo académico", "descripcion": "Consulte con su programa por tutorías, monitorías y estrategias de estudio."},
    {"titulo": "Salud mental y bienestar emocional", "descripcion": "Si siente estrés o ansiedad, Bienestar puede orientarlo hacia los servicios de apoyo disponibles."},
]


def get_config(db: Session) -> dict[str, Any]:
    """Configuración vigente: slice A (`aq10_config`) o, si no existe/está vacía, el modelo o la semilla en `data/aq10`."""
    if _get_active_config is not None:
        try:
            return _get_active_config(db).to_dict()
        except Exception:  # NotFound: el Admin aún no la cargó -> respaldo
            pass
    row = db.scalar(select(CuestionarioAQ10).where(CuestionarioAQ10.activo.is_(True)).order_by(CuestionarioAQ10.id.desc()))
    if row is None:
        row = CuestionarioAQ10(
            nombre="AQ-10 (Allison et al., 2012) - versión en español", version="1.0", fuente=aq10_data.FUENTE,
            items=aq10_data.items_json(), opciones=aq10_data.opciones_json(), punto_corte=aq10_data.PUNTO_CORTE,
            revision_linguistica_pendiente=True, activo=True,
        )
        db.add(row)
        db.flush()
    return {
        "id": row.id, "version": row.version, "nombre": row.nombre, "idioma": row.idioma, "fuente": row.fuente,
        "items": list(row.items), "opciones": list(row.opciones), "punto_corte": row.punto_corte,
        "instrucciones": PROTOCOLO_BIENVENIDA["pasos"][0], "revision_linguistica_pendiente": row.revision_linguistica_pendiente,
    }


def punto_corte(db: Session, cfg: dict[str, Any]) -> int:
    v = params.get_param(db, "aq10_punto_corte")
    return int(v if v is not None else cfg.get("punto_corte", 6))


def _direccion(opcion: dict) -> str:
    return opcion.get("direccion") or opcion.get("tipo")


def score(cfg: dict[str, Any], respuestas: dict[int, int]) -> int:
    """1 punto por ítem cuya respuesta cae del lado indicado en `puntua_si` (ACUERDO: opciones 1-2; DESACUERDO: 3-4)."""
    dir_por_valor = {int(o["valor"]): _direccion(o) for o in cfg["opciones"]}
    total = 0
    for it in cfg["items"]:
        valor = respuestas[int(it["numero"])]
        if dir_por_valor[valor] == it["puntua_si"]:
            total += 1
    return total


def validate_answers(cfg: dict[str, Any], raw: dict[int | str, int]) -> dict[int, int]:
    numeros = {int(i["numero"]) for i in cfg["items"]}
    valores = {int(o["valor"]) for o in cfg["opciones"]}
    try:
        resp = {int(k): int(v) for k, v in raw.items()}
    except (TypeError, ValueError):
        raise Unprocessable("Las respuestas deben ser números.", "AQ10_RESPUESTAS_INVALIDAS") from None
    faltan = sorted(numeros - set(resp))
    if faltan:
        raise Unprocessable(f"Falta responder los ítems: {', '.join(map(str, faltan))}.", "AQ10_INCOMPLETO",
                            extra={"faltan": faltan})
    if set(resp) - numeros:
        raise Unprocessable("Hay ítems que no existen en el cuestionario.", "AQ10_RESPUESTAS_INVALIDAS")
    if any(v not in valores for v in resp.values()):
        raise Unprocessable(f"Cada respuesta debe ser una de las opciones: {sorted(valores)}.", "AQ10_RESPUESTAS_INVALIDAS")
    return resp


def _bienestar_destinatarios(db: Session, est: Estudiante) -> list[int]:
    return [est.bienestar_asignado_id] if est.bienestar_asignado_id else get_notification_user_ids(db, "BIENESTAR")


def apply(db: Session, est: Estudiante, actor: Usuario, raw_answers: dict, request: Request | None = None) -> dict[str, Any]:
    cfg = get_config(db)
    es_estudiante = str(actor.rol) == Rol.ESTUDIANTE
    if es_estudiante:
        ult = db.scalar(select(RespuestaAQ10).where(RespuestaAQ10.estudiante_id == est.id).order_by(RespuestaAQ10.aplicado_at.desc()))
        if ult is not None and ult.aplicado_at > utcnow() - timedelta(days=DIAS_REAPLICACION_AUTOAPLICADA):
            raise Conflict(
                "Ya respondió el AQ-10 hace poco. Si quiere repetirlo, pida a Bienestar que lo aplique con usted.",
                "AQ10_YA_APLICADO",
            )
    resp = validate_answers(cfg, raw_answers)
    puntaje = score(cfg, resp)
    corte = punto_corte(db, cfg)
    supera = puntaje >= corte
    row = RespuestaAQ10(
        estudiante_id=est.id, cuestionario_id=cfg["id"], aplicado_por_id=actor.id,
        modalidad=ModalidadAQ10.AUTOAPLICADA if es_estudiante else ModalidadAQ10.ASISTIDA, aplicado_at=utcnow(),
        respuestas={str(k): v for k, v in sorted(resp.items())}, puntaje=puntaje, punto_corte_aplicado=corte,
        supera_umbral=supera, flujo_activado=False,
    )
    db.add(row)
    db.flush()
    # La auditoría NO guarda respuestas ni puntaje (audit.sanitize los enmascara).
    audit.log(db, actor, audit.Accion.APLICACION_AQ10, "respuesta_aq10", row.id,
              {"modalidad": str(row.modalidad), "cuestionario_version": cfg["version"], "supera_umbral": supera},
              request=request, estudiante_id=est.id)
    resultado: dict[str, Any] = {"mensaje_tamizaje": MENSAJE_TAMIZAJE}
    if supera:
        resultado.update(_activate_flow(db, est, actor, row, request))
    else:
        resultado.update({
            "ruta_maar_tea_activada": False,
            "mensaje": "El resultado quedó archivado. Esto no es un diagnóstico y no cierra ninguna puerta: si más adelante "
                       "quiere que lo revisemos de nuevo o siente dificultades académicas, puede volver a solicitarlo a Bienestar.",
            "recursos_bienestar": RECURSOS_BIENESTAR,
        })
    db.flush()
    return {"row": row, "puntaje": puntaje, "punto_corte": corte, "supera_umbral": supera, "cfg": cfg, **resultado}


def _activate_flow(db: Session, est: Estudiante, actor: Usuario, row: RespuestaAQ10, request) -> dict[str, Any]:
    row.flujo_activado = True
    car = db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == est.id))
    creada = False
    if car is None:  # F1 pendiente: el profesional responsable se reasigna a quien la edite primero
        prof = est.bienestar_asignado_id or (actor.id if str(actor.rol) == Rol.BIENESTAR else None)
        if prof is None:
            ids = get_notification_user_ids(db, "BIENESTAR")
            prof = ids[0] if ids else actor.id
        db.add(Caracterizacion(estudiante_id=est.id, fecha_caracterizacion=date.today(), profesional_responsable_id=prof,
                               estado=EstadoCaracterizacion.INCOMPLETA, version=1))
        creada = True
    u = db.get(Usuario, est.usuario_id)
    notify(db, Evento.AQ10_POSITIVO, _bienestar_destinatarios(db, est),
           {"estudiante_nombre": u.nombre_completo, "enlace": f"/bienestar/estudiantes/{est.id}"})
    audit.log(db, actor, AccionB.AQ10_FLUJO_ACTIVADO, "estudiante", est.id, {"f1_creada": creada}, request=request,
              estudiante_id=est.id)
    return {
        "ruta_maar_tea_activada": True, "f1_pendiente_creada": creada,
        "mensaje": "Gracias por responder. Con este resultado, Bienestar le propondrá conocer mejor cómo aprende "
                   "(caracterización) para construir juntos sus apoyos. Recuerde: es un tamizaje, no un diagnóstico.",
    }


def serialize(r: RespuestaAQ10, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": r.id, "estudiante_id": r.estudiante_id, "cuestionario_id": r.cuestionario_id,
        "modalidad": str(r.modalidad), "aplicado_at": r.aplicado_at.isoformat(), "aplicado_por_id": r.aplicado_por_id,
        "puntaje": r.puntaje, "punto_corte_aplicado": r.punto_corte_aplicado, "supera_umbral": r.supera_umbral,
        "flujo_activado": r.flujo_activado, "respuestas": r.respuestas, "mensaje_tamizaje": MENSAJE_TAMIZAJE,
    }
