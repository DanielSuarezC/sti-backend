"""Ayudas de las pruebas del slice C3 (datos sensibles centinela, recorrido recursivo del JSON)."""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    AjusteRazonable,
    Caracterizacion,
    CuestionarioAQ10,
    DatoComunicacion,
    EstrategiaDua,
    NotaContinuidad,
    RespuestaAQ10,
)
from app.models.base import utcnow
from app.models.enums import (
    DimensionDua,
    EstadoPlanEnum,
    ModalidadAQ10,
    Semaforo,
)
from tests.factories import make_plan_with_ajuste

CENTINELAS = [
    "CENTINELA_DIAGNOSTICO", "CENTINELA_F1_RESUMEN", "CENTINELA_F1_AUTODESC", "CENTINELA_COMUNICACION",
    "CENTINELA_NOTA_CONTINUIDAD", "Zoraida Quintero Mejia", "Ruido en el aula", "Reduce ruido y sobrecarga",
    "CENTINELA_COMENTARIO_ESTUDIANTE",
]

CLAVES_PROHIBIDAS = {
    "aq10", "aq_10", "puntaje", "respuestas_aq10", "diagnostico", "fecha_diagnostico_tea", "tipo_tea_caracterizacion",
    "institucion_diagnostico", "caracterizacion", "resumen_ejecutivo", "autodescripcion_estudiante", "f1", "f2",
    "barrera", "barreras", "barrera_asociada_id", "tipo_barrera", "justificacion", "notas_continuidad",
    "nota_continuidad", "contenido", "comentario_estudiante", "percepcion_estudiante", "nueva_barrera_detectada",
    "estudiante_id", "email", "nombre_completo", "codigo_estudiante", "numero_documento", "telefono",
}


def claves_recursivas(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k).lower())
            out |= claves_recursivas(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= claves_recursivas(v)
    return out


def assert_sin_datos_clinicos(payload, extra_permitidas: set[str] | None = None) -> None:
    """Falla si la respuesta JSON contiene una clave prohibida (a cualquier profundidad) o un valor centinela."""
    prohibidas = CLAVES_PROHIBIDAS - (extra_permitidas or set())
    encontradas = claves_recursivas(payload) & prohibidas
    assert not encontradas, f"claves prohibidas en la respuesta: {sorted(encontradas)}"
    texto = json.dumps(payload, ensure_ascii=False, default=str)
    for c in CENTINELAS:
        assert c not in texto, f"dato sensible filtrado: {c}"


def plan_con_datos_clinicos(db: Session, w, *, estado=EstadoPlanEnum.IMPLEMENTACION, asignatura=True):
    """Plan con ajuste en la asignatura del docente + datos clinicos centinela del estudiante."""
    w.estudiante_user.nombre_completo = "Zoraida Quintero Mejia"
    plan, ajuste = make_plan_with_ajuste(db, w.estudiante, w.bienestar, asignatura=w.asignatura if asignatura else None,
                                         estado=estado)
    ajuste.semaforo_actual = Semaforo.AMARILLO
    ajuste.frecuencia = "Cada clase"
    ajuste.indicador_efectividad = "Entrega a tiempo"
    w.estudiante.fecha_diagnostico_tea = date(2020, 5, 1)
    w.estudiante.tipo_tea_caracterizacion = "CENTINELA_DIAGNOSTICO"
    w.estudiante.institucion_diagnostico = "CENTINELA_DIAGNOSTICO"
    cuest = CuestionarioAQ10(nombre="AQ", version="t", items=[], opciones=[], punto_corte=6, activo=True)
    db.add(cuest)
    db.flush()
    db.add(RespuestaAQ10(
        estudiante_id=w.estudiante.id, cuestionario_id=cuest.id, aplicado_por_id=w.bienestar.id,
        modalidad=ModalidadAQ10.ASISTIDA, aplicado_at=utcnow(), respuestas={"1": 1}, puntaje=9,
        punto_corte_aplicado=6, supera_umbral=True))
    car = Caracterizacion(estudiante_id=w.estudiante.id, fecha_caracterizacion=date.today(),
                          profesional_responsable_id=w.bienestar.id, resumen_ejecutivo="CENTINELA_F1_RESUMEN",
                          autodescripcion_estudiante="CENTINELA_F1_AUTODESC")
    db.add(car)
    db.flush()
    db.add(DatoComunicacion(caracterizacion_id=car.id, tipo_comunicacion="Verbal", descripcion="CENTINELA_COMUNICACION"))
    db.add(NotaContinuidad(estudiante_id=w.estudiante.id, semestre_origen="2026-II", semestre_destino="2027-I",
                           contenido="CENTINELA_NOTA_CONTINUIDAD", elaborada_por_id=w.bienestar.id))
    db.commit()
    return plan, ajuste


def agregar_estrategia(db: Session, plan, w, asignatura=True) -> EstrategiaDua:
    e = EstrategiaDua(plan_id=plan.id, nombre_estrategia="Material anticipado", descripcion="Compartir diapositivas antes",
                      dimension_dua=DimensionDua.MULTIPLES_MEDIOS_PRESENTACION,
                      asignatura_id=w.asignatura.id if asignatura else None)
    db.add(e)
    db.commit()
    return e


def segundo_ajuste(db: Session, plan, base: AjusteRazonable, *, asignatura_id=None, nombre="Examen en sala aparte"):
    a = AjusteRazonable(plan_id=plan.id, barrera_asociada_id=base.barrera_asociada_id, nombre_ajuste=nombre,
                        descripcion_ajuste="Presentar el examen en un salón con menos estímulos",
                        justificacion="Reduce ruido y sobrecarga", tipo_ajuste=base.tipo_ajuste,
                        fecha_inicio=date.today(), asignatura_id=asignatura_id)
    db.add(a)
    db.commit()
    return a
