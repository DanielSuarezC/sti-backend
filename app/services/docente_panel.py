"""Panel del Docente (HU-23/24, D10, M3/M6).

PRIVACIDAD (D10): el docente solo ve ajustes y estrategias DUA de SUS asignaturas (o donde es responsable) en planes
APROBADO/IMPLEMENTACION/SEGUIMIENTO/FINALIZADO. Nunca: AQ-10, F1/F2, barreras, diagnostico, justificacion del ajuste,
comentarios/percepcion del estudiante ni notas de continuidad. El estudiante se muestra con un ALIAS ESTABLE.

Decision del alias: "Estudiante K7MQ" = HMAC-SHA256(secreto, docente|estudiante) -> 4 caracteres sin ambiguedad. Es estable
entre sesiones, distinto para cada docente (no sirve para cruzar informacion entre docentes) y no revela el id real.
Parametro `docente_ve_nombre` (PARAMETRO_SISTEMA, default false): si es true se agregan las INICIALES; el nombre completo
nunca se expone (Bienestar le indica al docente de quien se trata, p. ej. en la primera clase).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.permissions import (
    PLAN_ESTADOS_VISIBLES_DOCENTE,
    docente_ajuste_ids,
    docente_asignatura_ids_stmt,
    student_has_consent,
)
from app.core.security import _jwt_secret
from app.models.academico import Asignatura
from app.models.apoyos import Apoyo, ImplementacionApoyo, RegistroImplementacion, ResponsableApoyo
from app.models.base import utcnow
from app.models.enums import (
    EstadoApoyo,
    EstadoImplementacion,
    EstadoImplementacionDua,
    EstadoPlanEnum,
    TipoEvidenciaArchivo,
)
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea
from app.models.seguimiento import RegistroSeguimientoAjuste
from app.models.usuarios import Estudiante, Usuario
from app.services.params import get_param

_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PLAN_ESCRIBIBLE = (EstadoPlanEnum.APROBADO, EstadoPlanEnum.IMPLEMENTACION, EstadoPlanEnum.SEGUIMIENTO)
_CATEGORIAS = (
    ("resp_comunicacion", "tipo_comunicacion_ajuste"), ("resp_pedagogia", "tipo_pedagogico_ajuste"),
    ("resp_evaluacion", "tipo_evaluativo_ajuste"), ("resp_ambiente", "tipo_ambiental_ajuste"),
    ("resp_interaccion", "tipo_interaccion_ajuste"), ("resp_tecnologia", "tipo_tecnologico_ajuste"),
)


# ----------------------------------------------------------------------------- alias
def _alias_base(docente_id: int, estudiante_id: int, largo: int) -> str:
    digest = hmac.new(_jwt_secret().encode(), f"alias|{docente_id}|{estudiante_id}".encode(), hashlib.sha256).digest()
    return "".join(_ALFABETO[b % len(_ALFABETO)] for b in digest[:largo])


def mapa_alias(docente_id: int, estudiante_ids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    usados: set[str] = set()
    for eid in sorted(estudiante_ids):
        largo = 4
        while (a := _alias_base(docente_id, eid, largo)) in usados:
            largo += 1
        usados.add(a)
        out[eid] = f"Estudiante {a}"
    return out


def _iniciales(nombre: str) -> str:
    return "".join(p[0].upper() + "." for p in nombre.split() if p)


def docente_ve_nombre(db: Session) -> bool:
    return bool(get_param(db, "docente_ve_nombre", False))


# ----------------------------------------------------------------------------- consultas
def _con_consentimiento(db: Session, filas):
    consent: dict[int, bool] = {}
    out = []
    for obj, p in filas:
        if p.estudiante_id not in consent:
            consent[p.estudiante_id] = student_has_consent(db, p.estudiante_id)
        if consent[p.estudiante_id]:
            out.append((obj, p))
    return out


def _ajustes_en_alcance(db: Session, user: Usuario) -> list[tuple[AjusteRazonable, PlanMaarTea]]:
    ids = docente_ajuste_ids(db, user)
    if not ids:
        return []
    filas = db.execute(
        select(AjusteRazonable, PlanMaarTea).join(PlanMaarTea, PlanMaarTea.id == AjusteRazonable.plan_id)
        .where(AjusteRazonable.id.in_(ids), PlanMaarTea.estado.in_(PLAN_ESTADOS_VISIBLES_DOCENTE))
        .order_by(AjusteRazonable.id)
    ).all()
    return _con_consentimiento(db, filas)


def _estrategias_en_alcance(db: Session, user: Usuario) -> list[tuple[EstrategiaDua, PlanMaarTea]]:
    asig = docente_asignatura_ids_stmt(user)
    filas = db.execute(
        select(EstrategiaDua, PlanMaarTea).join(PlanMaarTea, PlanMaarTea.id == EstrategiaDua.plan_id)
        .where(PlanMaarTea.estado.in_(PLAN_ESTADOS_VISIBLES_DOCENTE),
               or_(EstrategiaDua.asignatura_id.in_(asig), EstrategiaDua.responsable_implementacion_id == user.id))
        .order_by(EstrategiaDua.id)
    ).all()
    return _con_consentimiento(db, filas)


def _asignatura_out(db: Session, asignatura_id: int | None) -> dict[str, Any] | None:
    a = db.get(Asignatura, asignatura_id) if asignatura_id else None
    return {"id": a.id, "codigo": a.codigo, "nombre": a.nombre} if a else None


def _impl_dict(imp: ImplementacionApoyo, ajuste_id: int) -> dict[str, Any]:
    reg = imp.registros[0] if imp.registros else None
    return {
        "id": imp.id, "ajuste_id": ajuste_id, "implementado": str(imp.estado) == EstadoImplementacion.EJECUTADA,
        "fecha": imp.fecha_implementacion, "nota": reg.nota if reg else imp.observaciones,
        "registrado_at": reg.fecha_registro if reg else imp.created_at,
    }


def _impls_stmt(user: Usuario, ajuste_id: int):
    return (
        select(ImplementacionApoyo)
        .join(ResponsableApoyo, ResponsableApoyo.id == ImplementacionApoyo.responsable_apoyo_id)
        .join(Apoyo, Apoyo.id == ResponsableApoyo.apoyo_id)
        .where(Apoyo.ajuste_id == ajuste_id, ResponsableApoyo.usuario_responsable_id == user.id)
        .order_by(ImplementacionApoyo.fecha_implementacion.desc(), ImplementacionApoyo.id.desc())
    )


def _ajuste_dict(db: Session, user: Usuario, a: AjusteRazonable, p: PlanMaarTea) -> dict[str, Any]:
    cats = [str(getattr(r, attr)) for rel, attr in _CATEGORIAS for r in getattr(a, rel)]
    imp = db.scalar(_impls_stmt(user, a.id).limit(1))
    ult = _impl_dict(imp, a.id) if imp else None
    return {
        "id": a.id, "nombre_ajuste": a.nombre_ajuste, "descripcion": a.descripcion_ajuste,
        "tipo_ajuste": str(a.tipo_ajuste), "categorias": cats, "frecuencia": a.frecuencia,
        "indicador_efectividad": a.indicador_efectividad, "actividad_si_aplica": a.actividad_si_aplica,
        "fecha_inicio": a.fecha_inicio, "fecha_fin_prevista": a.fecha_fin_prevista,
        "permanencia_indefinida": a.permanencia_indefinida, "estado": str(a.estado),
        "semaforo_actual": str(a.semaforo_actual) if a.semaforo_actual else None, "semestre": p.semestre_academico,
        "plan_estado": str(p.estado), "es_responsable": a.responsable_id == user.id,
        "ultima_implementacion": ({"id": ult["id"], "fecha": ult["fecha"], "implementado": ult["implementado"],
                                   "nota": ult["nota"]} if ult else None),
    }


def _estrategia_dict(e: EstrategiaDua, p: PlanMaarTea) -> dict[str, Any]:
    return {
        "id": e.id, "nombre_estrategia": e.nombre_estrategia, "descripcion": e.descripcion,
        "dimension_dua": str(e.dimension_dua), "alcance": e.alcance,
        "escenario": str(e.escenario) if e.escenario else None,
        "estado_implementacion": str(e.estado_implementacion),
        "implementada": str(e.estado_implementacion) == EstadoImplementacionDua.IMPLEMENTADA,
        "nota_implementacion": e.nota_implementacion, "implementada_at": e.implementada_at,
        "semestre": p.semestre_academico, "plan_estado": str(p.estado),
    }


def _alias_e_iniciales(db: Session, user: Usuario, ajs, ests) -> tuple[dict[int, str], dict[int, str | None]]:
    est_ids = {p.estudiante_id for _a, p in ajs} | {p.estudiante_id for _e, p in ests}
    alias = mapa_alias(user.id, est_ids)
    ini: dict[int, str | None] = dict.fromkeys(est_ids)
    if docente_ve_nombre(db):
        for eid in est_ids:
            est = db.get(Estudiante, eid)
            u = db.get(Usuario, est.usuario_id) if est else None
            ini[eid] = _iniciales(u.nombre_completo) if u else None
    return alias, ini


# ----------------------------------------------------------------------------- casos de uso
def mis_ajustes(db: Session, user: Usuario) -> dict[str, Any]:
    ajs, ests = _ajustes_en_alcance(db, user), _estrategias_en_alcance(db, user)
    alias, ini = _alias_e_iniciales(db, user, ajs, ests)
    grupos: dict[int | None, dict[int, dict[str, Any]]] = {}

    def _slot(asig_id: int | None, est_id: int) -> dict[str, Any]:
        return grupos.setdefault(asig_id, {}).setdefault(
            est_id, {"alias": alias[est_id], "iniciales": ini[est_id], "ajustes": [], "estrategias_dua": []})

    for a, p in ajs:
        _slot(a.asignatura_id, p.estudiante_id)["ajustes"].append(_ajuste_dict(db, user, a, p))
    for e, p in ests:
        _slot(e.asignatura_id, p.estudiante_id)["estrategias_dua"].append(_estrategia_dict(e, p))
    asignaturas = []
    for asig_id in sorted(grupos, key=lambda x: (x is None, x or 0)):
        estudiantes = sorted(grupos[asig_id].values(), key=lambda s: s["alias"])
        asignaturas.append({"asignatura": _asignatura_out(db, asig_id), "estudiantes": estudiantes})
    return {"docente_ve_nombre": docente_ve_nombre(db), "total_ajustes": len(ajs), "total_estrategias": len(ests),
            "asignaturas": asignaturas}


def _ajuste_en_alcance_or_404(db: Session, user: Usuario, ajuste_id: int) -> tuple[AjusteRazonable, PlanMaarTea]:
    for a, p in _ajustes_en_alcance(db, user):
        if a.id == ajuste_id:
            return a, p
    # 404 (no 403) para no revelar que el ajuste existe en otra asignatura
    raise NotFound("No encontramos ese ajuste entre los de sus asignaturas.", "AJUSTE_NO_ENCONTRADO")


def _cortes(db: Session, ajuste_id: int) -> list[dict[str, Any]]:
    regs = db.scalars(select(RegistroSeguimientoAjuste).where(RegistroSeguimientoAjuste.ajuste_id == ajuste_id)
                      .order_by(RegistroSeguimientoAjuste.corte)).all()
    return [{"corte": str(r.corte), "semaforo": str(r.semaforo) if r.semaforo else None, "implementado": r.implementado}
            for r in regs]


def detalle_ajuste(db: Session, user: Usuario, ajuste_id: int) -> dict[str, Any]:
    a, p = _ajuste_en_alcance_or_404(db, user, ajuste_id)
    alias, ini = _alias_e_iniciales(db, user, _ajustes_en_alcance(db, user), _estrategias_en_alcance(db, user))
    out = _ajuste_dict(db, user, a, p)
    out.update({"alias": alias[p.estudiante_id], "iniciales": ini[p.estudiante_id],
                "asignatura": _asignatura_out(db, a.asignatura_id), "cortes": _cortes(db, a.id)})
    return out


def semaforo(db: Session, user: Usuario) -> dict[str, Any]:
    ajs = _ajustes_en_alcance(db, user)
    alias, _ = _alias_e_iniciales(db, user, ajs, [])
    resumen = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0, "SIN_REGISTRO": 0}
    filas = []
    for a, p in ajs:
        sem = str(a.semaforo_actual) if a.semaforo_actual else None
        resumen[sem or "SIN_REGISTRO"] += 1
        filas.append({"ajuste_id": a.id, "nombre_ajuste": a.nombre_ajuste, "alias": alias[p.estudiante_id],
                      "asignatura": _asignatura_out(db, a.asignatura_id), "semaforo_actual": sem,
                      "cortes": _cortes(db, a.id)})
    return {"resumen": resumen, "ajustes": filas}


def _validar_fecha(fecha: date) -> None:
    if fecha > date.today():
        raise Unprocessable("La fecha de implementación no puede ser futura. Registre lo que ya hizo.", "FECHA_FUTURA")


def registrar_implementacion(db: Session, user: Usuario, ajuste_id: int, implementado: bool, fecha: date,
                             nota: str | None, request=None) -> dict[str, Any]:
    a, p = _ajuste_en_alcance_or_404(db, user, ajuste_id)
    if p.estado not in _PLAN_ESCRIBIBLE:
        raise Conflict("El plan ya fue finalizado: no se pueden registrar nuevas implementaciones.",
                       "PLAN_NO_IMPLEMENTABLE")
    _validar_fecha(fecha)
    apoyo = db.scalar(select(Apoyo).where(Apoyo.ajuste_id == a.id).order_by(Apoyo.id))
    if apoyo is None:  # la matriz F7 aun no definio el apoyo: se crea el vinculo minimo para poder registrar
        apoyo = Apoyo(plan_id=p.id, ajuste_id=a.id, nombre_apoyo=a.nombre_ajuste, descripcion_apoyo=a.descripcion_ajuste,
                      tipo_apoyo="AJUSTE_RAZONABLE", fecha_inicio=a.fecha_inicio, estado=EstadoApoyo.ACTIVO)
        db.add(apoyo)
        db.flush()
    resp = db.scalar(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == apoyo.id,
                                                    ResponsableApoyo.usuario_responsable_id == user.id))
    if resp is None:
        resp = ResponsableApoyo(apoyo_id=apoyo.id, usuario_responsable_id=user.id, cargo_responsable="Docente",
                                fecha_asignacion=date.today(), es_principal=a.responsable_id == user.id,
                                frecuencia=a.frecuencia)
        db.add(resp)
        db.flush()
    imp = ImplementacionApoyo(
        responsable_apoyo_id=resp.id, fecha_implementacion=fecha, descripcion_actividad=a.nombre_ajuste,
        observaciones=nota, estado=EstadoImplementacion.EJECUTADA if implementado else EstadoImplementacion.PENDIENTE)
    db.add(imp)
    db.flush()
    db.add(RegistroImplementacion(implementacion_id=imp.id, nota=nota, registrado_por_id=user.id,
                                  tipo_evidencia=TipoEvidenciaArchivo.NOTA_OBSERVACION))
    db.flush()
    db.refresh(imp, attribute_names=["registros"])
    audit.log(db, user, "IMPLEMENTACION_AJUSTE_REGISTRADA", "implementacion_apoyo", imp.id,
              {"ajuste_id": a.id, "implementado": implementado, "fecha": fecha.isoformat()},
              request=request, estudiante_id=p.estudiante_id)
    return _impl_dict(imp, a.id)


def historial_implementacion(db: Session, user: Usuario, ajuste_id: int) -> list[dict[str, Any]]:
    a, _p = _ajuste_en_alcance_or_404(db, user, ajuste_id)
    return [_impl_dict(i, a.id) for i in db.scalars(_impls_stmt(user, a.id)).all()]


_ORDEN = {"PLANEADA": 0, "INICIADA": 1, "IMPLEMENTADA": 2}


def registrar_estrategia(db: Session, user: Usuario, estrategia_id: int, estado: str, fecha: date | None,
                         nota: str | None, request=None) -> dict[str, Any]:
    par = next(((e, p) for e, p in _estrategias_en_alcance(db, user) if e.id == estrategia_id), None)
    if par is None:
        raise NotFound("No encontramos esa estrategia entre las de sus asignaturas.", "ESTRATEGIA_NO_ENCONTRADA")
    e, p = par
    if p.estado not in _PLAN_ESCRIBIBLE:
        raise Conflict("El plan ya fue finalizado: no se pueden registrar nuevas implementaciones.",
                       "PLAN_NO_IMPLEMENTABLE")
    actual = str(e.estado_implementacion)
    if actual not in _ORDEN or _ORDEN[estado] <= _ORDEN[actual]:
        raise Conflict(
            f"La estrategia está en {actual}; solo puede avanzar PLANEADA → INICIADA → IMPLEMENTADA.",
            "TRANSICION_ESTRATEGIA_INVALIDA")
    fecha = fecha or date.today()
    _validar_fecha(fecha)
    e.estado_implementacion = estado
    e.implementada = estado == "IMPLEMENTADA"
    e.nota_implementacion = nota if nota is not None else e.nota_implementacion
    e.implementada_por_id = user.id
    e.implementada_at = utcnow()
    if estado == "INICIADA" and e.fecha_inicio_implementacion is None:
        e.fecha_inicio_implementacion = fecha
    db.flush()
    audit.log(db, user, "IMPLEMENTACION_ESTRATEGIA_DUA", "estrategia_dua", e.id, {"estado": estado},
              request=request, estudiante_id=p.estudiante_id)
    return {"id": e.id, "estado_implementacion": estado, "implementada": estado == "IMPLEMENTADA",
            "nota_implementacion": e.nota_implementacion, "implementada_at": e.implementada_at}
