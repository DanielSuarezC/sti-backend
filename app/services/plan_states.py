"""Máquina de estados del Plan MAAR-TEA (BUILD_SPEC §4) y transiciones permitidas.

    BORRADOR -> EN_CONCERTACION -> PENDIENTE_VALIDACION -> PENDIENTE_FIRMAS -> APROBADO -> IMPLEMENTACION
             -> SEGUIMIENTO -> FINALIZADO -> ARCHIVADO
    + EN_NEGOCIACION (el estudiante objeta; hasta 3 ciclos) y ESCALADO_COMITE (sin acuerdo tras 3 ciclos).

Este módulo es la ÚNICA fuente de verdad de las transiciones: el seed la vuelca en ESTADO_PLAN y los servicios
la usan con `assert_transition`. Cualquier cambio de estado debe pasar por aquí.
"""

from __future__ import annotations

from app.core.errors import Conflict
from app.models.enums import EstadoPlanEnum as S

TRANSICIONES: dict[S, tuple[S, ...]] = {
    S.BORRADOR: (S.EN_CONCERTACION, S.ARCHIVADO),
    S.EN_CONCERTACION: (S.EN_NEGOCIACION, S.PENDIENTE_VALIDACION, S.BORRADOR, S.ARCHIVADO),
    S.EN_NEGOCIACION: (S.EN_CONCERTACION, S.ESCALADO_COMITE, S.ARCHIVADO),
    S.ESCALADO_COMITE: (S.EN_CONCERTACION, S.PENDIENTE_VALIDACION, S.ARCHIVADO),
    S.PENDIENTE_VALIDACION: (S.PENDIENTE_FIRMAS, S.EN_CONCERTACION, S.BORRADOR),
    S.PENDIENTE_FIRMAS: (S.APROBADO, S.EN_CONCERTACION, S.BORRADOR),
    S.APROBADO: (S.IMPLEMENTACION, S.EN_CONCERTACION),  # una modificación reabre la concertación (nueva versión)
    S.IMPLEMENTACION: (S.SEGUIMIENTO, S.EN_CONCERTACION),
    S.SEGUIMIENTO: (S.FINALIZADO, S.EN_CONCERTACION),
    S.FINALIZADO: (S.ARCHIVADO,),
    S.ARCHIVADO: (),
}

DESCRIPCIONES: dict[S, str] = {
    S.BORRADOR: "Borrador asistido elaborado por Bienestar a partir de barreras y sugerencias DUA.",
    S.EN_CONCERTACION: "Bienestar y el estudiante revisan, aceptan o proponen cambios al plan.",
    S.EN_NEGOCIACION: "El estudiante objetó un ajuste; hay un ciclo de negociación abierto (máximo 3).",
    S.ESCALADO_COMITE: "No hubo acuerdo tras 3 ciclos; el caso pasó al Comité de Inclusión institucional.",
    S.PENDIENTE_VALIDACION: "El estudiante aceptó; espera validación del Coordinador del programa.",
    S.PENDIENTE_FIRMAS: "Validado; faltan firmas digitales del estudiante, Bienestar y Coordinador.",
    S.APROBADO: "Firmado por los tres actores. Vigente para el semestre.",
    S.IMPLEMENTACION: "Los docentes y responsables ejecutan los ajustes y apoyos.",
    S.SEGUIMIENTO: "Seguimiento por cortes C1, C2 y C3 con semáforo por ajuste.",
    S.FINALIZADO: "Semestre evaluado (F9) y plan cerrado.",
    S.ARCHIVADO: "Plan archivado (conservado para trazabilidad, no editable).",
}

#: Estados en los que el plan se considera ACTIVO para el semestre (cuenta para el índice único parcial).
ESTADOS_ACTIVOS = tuple(s for s in S if s != S.ARCHIVADO)
#: Estados en los que el plan ya está firmado y vigente (visible para el docente).
ESTADOS_VIGENTES = (S.APROBADO, S.IMPLEMENTACION, S.SEGUIMIENTO, S.FINALIZADO)
#: Estados editables por Bienestar sin generar una nueva versión.
ESTADOS_EDITABLES = (S.BORRADOR, S.EN_CONCERTACION, S.EN_NEGOCIACION, S.ESCALADO_COMITE)


def can_transition(origen: S | str, destino: S | str) -> bool:
    return S(str(destino)) in TRANSICIONES[S(str(origen))]


def assert_transition(origen: S | str, destino: S | str) -> None:
    if not can_transition(origen, destino):
        permitidos = ", ".join(t.value for t in TRANSICIONES[S(str(origen))]) or "ninguno"
        raise Conflict(
            f"El plan no puede pasar de {S(str(origen)).value} a {S(str(destino)).value}. "
            f"Desde este estado solo puede pasar a: {permitidos}.",
            "TRANSICION_PLAN_INVALIDA",
        )
