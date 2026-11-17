"""Semilla adicional del slice C1 (datos ficticios de demostración): planes coherentes para est4 y est5.

Requiere la demo base (`SEED_DEMO=1 python -m scripts.seed`). Uso:

    python -m scripts.seed_extra_c1        # o desde código: seed_extra_c1.seed(db)

* est5: su plan en IMPLEMENTACION queda sellado (v1 firmada) y se amplía en una v2 con ajustes de las 6 categorías,
  recorrida por el workflow real (aceptación, validación, 3 firmas, matriz F7, aceptación del docente, implementación).
* est4: plan en NEGOCIACIÓN (el estudiante objetó un ajuste; ciclo 2 abierto), con una propuesta de modificación pendiente.
Es idempotente: si ya existe el plan de est4 o est5 ya tiene sus 6 categorías, no repite.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.models import (
    AjusteRazonable,
    Asignatura,
    BarreraIdentificada,
    Estudiante,
    Facilitador,
    FirmaPlan,
    ImplementacionApoyo,
    PlanMaarTea,
    PlanVersion,
    ResponsableApoyo,
    Usuario,
)
from app.models.apoyos import Apoyo
from app.models.base import utcnow
from app.models.dua import EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import (
    EstadoBarrera,
    EstadoFirma,
    EstadoImplementacion,
    EstadoPlanEnum,
    EstadoSugerencia,
    RolFirmante,
    TipoBarrera,
    TipoFacilitador,
)
from app.models.mapa import BarreraSocial
from app.services import negotiation
from app.services import plan_builder as builder
from app.services import plan_signatures as sig
from app.services import plan_workflow as wf
from scripts.seed import DEMO_DOMAIN, SEMESTRE

logger = logging.getLogger("sti.seed_c1")


def _usuario(db: Session, clave: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == f"{clave}.demo@{DEMO_DOMAIN}"))


def _estudiante(db: Session, usuario: Usuario) -> Estudiante:
    return db.scalar(select(Estudiante).where(Estudiante.usuario_id == usuario.id))


def _barrera(db, est, bienestar, tipo, desc, *, escenario=None):
    b = BarreraIdentificada(estudiante_id=est.id, tipo_barrera=tipo, descripcion_barrera=f"(Demo) {desc}",
                            fecha_identificacion=date(2026, 8, 14), estado=EstadoBarrera.PERSISTENTE,
                            semestre_academico=SEMESTRE, registrada_por_id=bienestar.id, escenario=escenario,
                            impacto_aprendizaje=True)
    db.add(b)
    db.flush()
    return b


def _sellar_v1(db: Session, plan: PlanMaarTea, bienestar: Usuario, coordinador: Usuario, estudiante: Usuario) -> None:
    """Re-sella la v1 de la semilla base con el hash canónico real y 3 firmas verificables."""
    for pv in db.scalars(select(PlanVersion).where(PlanVersion.plan_id == plan.id, PlanVersion.version == plan.version)):
        pv.soft_delete(bienestar.id, "Re-sellado por la semilla C1 (hash canónico)")
    for f in db.scalars(select(FirmaPlan).where(FirmaPlan.plan_id == plan.id)):
        f.soft_delete(bienestar.id, "Re-sellado por la semilla C1 (hash canónico)")
    db.flush()
    sig.congelar_version(db, plan, bienestar)
    h = sig.hash_contenido(sig.contenido_canonico(db, plan))
    base = utcnow() - timedelta(days=80)
    for i, (rol, u) in enumerate(((RolFirmante.ESTUDIANTE, estudiante), (RolFirmante.BIENESTAR, bienestar),
                                  (RolFirmante.COORDINADOR, coordinador))):
        ts = base + timedelta(hours=i * 5)
        db.add(FirmaPlan(plan_id=plan.id, version=plan.version, rol_firmante=rol, firmante_id=u.id, firmado_at=ts,
                         hash_documento=h, firma_hash=sig.calcular_firma_hash(h, plan.id, plan.version, rol.value, u.id, ts),
                         ip="127.0.0.1", user_agent="seed", estado=EstadoFirma.FIRMADA))
    db.flush()


def _seed_est5(db: Session, bienestar, coordinador, docente, u5, e5, asig) -> dict:
    plan = db.scalar(select(PlanMaarTea).where(PlanMaarTea.estudiante_id == e5.id,
                                               PlanMaarTea.semestre_academico == SEMESTRE))
    if plan is None:
        return {"est5": "sin plan base (ejecute scripts.seed con SEED_DEMO=1)"}
    n = len(list(db.scalars(select(AjusteRazonable.id).where(AjusteRazonable.plan_id == plan.id))))
    if n >= 6:
        return {"est5": "ya sembrado"}
    _sellar_v1(db, plan, bienestar, coordinador, u5)
    wf.preparar_edicion(db, plan, bienestar, "Ampliación del plan con ajustes de las 6 categorías (demo C1)")
    barrera_base = db.scalar(select(BarreraIdentificada).where(BarreraIdentificada.estudiante_id == e5.id))
    b_com = _barrera(db, e5, bienestar, TipoBarrera.COMUNICATIVA, "Instrucciones orales rápidas sin soporte escrito")
    b_ped = _barrera(db, e5, bienestar, TipoBarrera.PEDAGOGICA, "Material de clase entregado el mismo día")
    b_eva = _barrera(db, e5, bienestar, TipoBarrera.EVALUATIVA, "Exámenes con poco tiempo y mucho ruido")
    b_soc = _barrera(db, e5, bienestar, TipoBarrera.SOCIAL, "Trabajos en grupo sin roles definidos")
    db.add(BarreraSocial(barrera_id=b_soc.id, tipo_interaccion="Trabajo en grupo",
                         propuesta_respuesta_institucional="Capacitación breve a docentes sobre roles en trabajo grupal"))
    b_tec = _barrera(db, e5, bienestar, TipoBarrera.TECNOLOGICA, "La plataforma virtual cambia de formato sin aviso")
    db.add(Facilitador(estudiante_id=e5.id, tipo_facilitador=TipoFacilitador.PEDAGOGICO,
                       nombre_facilitador="(Demo) Guías escritas del docente", descripcion_detallada="Algunos docentes comparten guías.",
                       fecha_identificacion=date(2026, 8, 14), registrado_por_id=bienestar.id))
    db.flush()
    fort = builder.fortalezas_de(db, e5.id)
    fid = fort[0].id if fort else None
    base = {"asignatura_id": asig.id, "responsable_id": docente.id, "fortaleza_apoyo_id": fid, "frecuencia": "Cada sesión"}
    nuevos = [
        {"tipo_ajuste": "COMUNICACION", "detalle": {"tipo": "INSTRUCCIONES_ESCRITAS", "descripcion": "Indicaciones por escrito en la plataforma"},
         "nombre_ajuste": "Instrucciones escritas de cada actividad", "descripcion_ajuste": "Publicar por escrito las instrucciones y cambios antes de la clase.",
         "barrera_asociada_id": b_com.id, "indicador_efectividad": "No necesita pedir repetición de instrucciones", **base},
        {"tipo_ajuste": "PEDAGOGIA", "detalle": {"tipo": "MATERIALES_ANTICIPADOS"}, "nombre_ajuste": "Materiales con 48 horas de anticipación",
         "descripcion_ajuste": "Compartir guías y lecturas dos días antes.", "barrera_asociada_id": b_ped.id, "recurso": "Aula virtual",
         "indicador_efectividad": "Llega preparado a la sesión", **base},
        {"tipo_ajuste": "EVALUACION", "detalle": {"tipo": "TIEMPO_EXTENDIDO", "descripcion": "50 % de tiempo adicional"},
         "nombre_ajuste": "Tiempo adicional en exámenes", "descripcion_ajuste": "Tiempo extendido y salón con poco ruido para evaluaciones.",
         "barrera_asociada_id": b_eva.id, "recurso": "Salón reservado", "indicador_efectividad": "Completa el examen sin interrupciones", **base},
        {"tipo_ajuste": "INTERACCION", "detalle": {"tipo": "ROL_DEFINIDO", "descripcion": "Rol acordado antes de iniciar"},
         "nombre_ajuste": "Rol definido en trabajos en grupo", "descripcion_ajuste": "Asignar un rol claro y mediación docente en equipos.",
         "barrera_asociada_id": b_soc.id, "responsable_id": docente.id, "fortaleza_apoyo_id": fid, "asignatura_id": asig.id,
         "indicador_efectividad": "Participa en el equipo con un rol claro"},
        {"tipo_ajuste": "TECNOLOGIA", "detalle": {"tipo": "ACCESO_ANTICIPADO", "soporte_tecnico_requerido": True},
         "nombre_ajuste": "Aviso de cambios en la plataforma", "descripcion_ajuste": "Avisar cambios de formato y dar acceso anticipado a la plataforma.",
         "barrera_asociada_id": b_tec.id, "responsable_id": bienestar.id, "recurso": "Soporte de la oficina de TIC",
         "indicador_efectividad": "Usa la plataforma sin ayuda adicional"},
    ]
    creados = [builder.crear_ajuste(db, plan, bienestar, d) for d in nuevos]
    for a in creados:
        wf.respuesta_estudiante(db, plan, a, u5, "ACEPTADO", None)
    # el ajuste original (barrera_base) conserva su aceptación; cada paso usa el workflow real
    wf.enviar_a_validacion(db, plan, bienestar)
    wf.validar(db, plan, coordinador, "Validado: ajustes coherentes con el mapa de barreras.")
    for u in (u5, bienestar, coordinador):
        sig.firmar(db, plan, u)
    for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id, AjusteRazonable.responsable_id == docente.id)):
        wf.aceptacion_docente(db, plan, a, docente, True, "Entendido; lo aplico en mis clases.")
    if plan.estado == EstadoPlanEnum.APROBADO and builder.tiene_matriz(db, plan.id):
        wf.iniciar_implementacion(db, plan, bienestar)
    # implementaciones registradas: 3 de los apoyos para que la tasa de implementación sea calculable
    ejecutados = 0
    for ap in db.scalars(select(Apoyo).where(Apoyo.plan_id == plan.id).order_by(Apoyo.id)):
        if ejecutados >= 4:
            break
        r = db.scalar(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == ap.id, ResponsableApoyo.es_principal.is_(True)))
        if r is not None:
            db.add(ImplementacionApoyo(responsable_apoyo_id=r.id, fecha_implementacion=date(2026, 9, 10) + timedelta(days=ejecutados),
                                       estado=EstadoImplementacion.EJECUTADA, descripcion_actividad="(Demo) Apoyo aplicado en clase"))
            ejecutados += 1
    db.flush()
    return {"est5": f"plan {plan.id} v{plan.version} {plan.estado}, ajustes={len(creados) + n}, barrera_base={barrera_base.id if barrera_base else None}"}


def _seed_est4(db: Session, bienestar, u4, e4) -> dict:
    if db.scalar(select(PlanMaarTea.id).where(PlanMaarTea.estudiante_id == e4.id)):
        return {"est4": "ya sembrado"}
    _barrera(db, e4, bienestar, TipoBarrera.SENSORIAL, "Ruido de pasillo y timbres durante las clases")
    b_com = _barrera(db, e4, bienestar, TipoBarrera.COMUNICATIVA, "Instrucciones orales rápidas")
    _barrera(db, e4, bienestar, TipoBarrera.EVALUATIVA, "Exámenes con tiempo limitado")
    _barrera(db, e4, bienestar, TipoBarrera.TECNOLOGICA, "Plataforma con navegación poco clara")
    db.add(Facilitador(estudiante_id=e4.id, tipo_facilitador=TipoFacilitador.PEDAGOGICO, nombre_facilitador="(Demo) Guías escritas",
                       descripcion_detallada="Algunos docentes comparten guías.", fecha_identificacion=date(2026, 8, 14),
                       registrado_por_id=bienestar.id))
    cat = db.scalar(select(EstrategiaDuaCatalogo).where(EstrategiaDuaCatalogo.punto_verificacion == "1.1").order_by(EstrategiaDuaCatalogo.id)) \
        or db.scalar(select(EstrategiaDuaCatalogo).order_by(EstrategiaDuaCatalogo.id))
    if cat is not None:
        db.add(SugerenciaDua(estudiante_id=e4.id, barrera_id=b_com.id, estrategia_catalogo_id=cat.id, tipo_barrera=TipoBarrera.COMUNICATIVA,
                             principio_dua=cat.principio, estado=EstadoSugerencia.ACEPTADA, decidido_por_id=bienestar.id,
                             decidido_at=utcnow(), justificacion="(Demo) Pertinente para la barrera comunicativa en el aula."))
    db.flush()
    plan, _ = builder.crear_borrador(db, e4, bienestar, resumen_ejecutivo="(Demo) Plan en concertación con negociación abierta.")
    wf.enviar_a_estudiante(db, plan, bienestar)
    por_tipo = {str(a.tipo_ajuste): a for a in db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id))}
    wf.respuesta_estudiante(db, plan, por_tipo["COMUNICACION"], u4, "ACEPTADO", None)
    wf.respuesta_estudiante(db, plan, por_tipo["TECNOLOGIA"], u4, "MODIFICACION_PROPUESTA",
                            "Prefiero que el aviso llegue por correo y no solo en la plataforma.")
    wf.respuesta_estudiante(db, plan, por_tipo["EVALUACION"], u4, "ACEPTADO", None)
    objetado = por_tipo["AMBIENTE"]
    res = wf.respuesta_estudiante(db, plan, objetado, u4, "OBJETADO",
                                  "No quiero que me ubiquen aparte del grupo; prefiero tapones auditivos en mi lugar.")
    tarea = negotiation.get_tarea(db, res["negociacion"]["id"])
    negotiation.contrapropuesta(db, tarea, bienestar, "Mantener su lugar y ofrecer protección auditiva, con revisión en el primer corte.",
                                {"descripcion_ajuste": "Permanece en su lugar con protección auditiva y ubicación lejos de la puerta."})
    negotiation.responder(db, tarea, u4, False, "Aún prefiero hablarlo con la coordinación del programa antes de aceptar.")
    return {"est4": f"plan {plan.id} {plan.estado}; negociación {tarea.id} ciclo {tarea.ciclo} {tarea.estado}"}


def seed(db: Session) -> dict:
    """Siembra los planes demo de est4 y est5. Devuelve un resumen (no hace commit: el llamador decide)."""
    bienestar, coordinador, docente = _usuario(db, "bienestar"), _usuario(db, "coordinador"), _usuario(db, "docente")
    u4, u5 = _usuario(db, "est4"), _usuario(db, "est5")
    if not all((bienestar, coordinador, docente, u4, u5)):
        return {"omitido": "faltan los usuarios demo; ejecute primero `SEED_DEMO=1 python -m scripts.seed`"}
    asig = db.scalar(select(Asignatura).where(Asignatura.codigo == "ENF101"))
    out = {}
    out.update(_seed_est5(db, bienestar, coordinador, docente, u5, _estudiante(db, u5), asig))
    out.update(_seed_est4(db, bienestar, u4, _estudiante(db, u4)))
    db.flush()
    return out


def main() -> None:
    with session_scope() as db:
        resultado = seed(db)
    for k, v in resultado.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
