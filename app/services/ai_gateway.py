"""ÚNICO punto del sistema que habla con OpenAI (RF-11, RF-16, D4).

Privacidad por construcción:
* La única entrada es `AIPromptInput(tipo_barrera, escenario, principio_dua)`, validada contra los enums del dominio.
  Cualquier otro dato (nombre, puntaje AQ-10, diagnóstico, ids...) lanza `AIPrivacyError`.
* El mensaje que viaja a la IA es un JSON con EXACTAMENTE esos tres campos; el resto es un prompt de sistema fijo.
* Este módulo NO importa el módulo AQ-10 ni los modelos de usuario/estudiante (hay una prueba que lo verifica).
* Sin `OPENAI_API_KEY`, sin la librería `langchain_openai` o ante cualquier error, devuelve una plantilla determinista.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields
from typing import Any

from app.core.config import get_settings
from app.models.enums import Escenario, PrincipioDua, TipoBarrera

logger = logging.getLogger("sti.ai_gateway")

SYSTEM_PROMPT = (
    "Eres un asesor pedagógico en diseño universal para el aprendizaje (DUA) para educación superior. Recibirás un JSON "
    "con tres campos: tipo_barrera, escenario y principio_dua. Escribe en español colombiano, con lenguaje claro y directo, "
    "un texto breve (máximo 120 palabras) dirigido a un docente universitario que explique cómo ajustar sus instrucciones "
    "o su clase para reducir esa barrera del entorno en ese escenario, siguiendo ese principio. No hables de personas "
    "concretas ni de diagnósticos: la barrera es del entorno, no del estudiante."
)

CAMPOS_PERMITIDOS = ("tipo_barrera", "escenario", "principio_dua")


class AIPrivacyError(ValueError):
    """Se intentó enviar a la IA un dato que no está permitido (RF-11/RF-16)."""


@dataclass(frozen=True, slots=True)
class AIPromptInput:
    tipo_barrera: TipoBarrera
    escenario: Escenario
    principio_dua: PrincipioDua

    def __post_init__(self) -> None:
        for name, enum_cls in (("tipo_barrera", TipoBarrera), ("escenario", Escenario), ("principio_dua", PrincipioDua)):
            value = getattr(self, name)
            try:
                coerced = enum_cls(value)
            except ValueError:
                raise AIPrivacyError(f"El campo «{name}» debe ser un valor válido de {enum_cls.__name__}.") from None
            object.__setattr__(self, name, coerced)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AIPromptInput:
        extra = set(data) - set(CAMPOS_PERMITIDOS)
        if extra:
            raise AIPrivacyError(
                "Solo se permiten tipo_barrera, escenario y principio_dua; no se puede enviar a la IA: "
                + ", ".join(sorted(extra))
            )
        faltan = set(CAMPOS_PERMITIDOS) - set(data)
        if faltan:
            raise AIPrivacyError("Faltan campos: " + ", ".join(sorted(faltan)))
        return cls(**{k: data[k] for k in CAMPOS_PERMITIDOS})

    def to_payload(self) -> dict[str, str]:
        return {f.name: str(getattr(self, f.name)) for f in fields(self)}


@dataclass(frozen=True)
class AIResult:
    texto: str
    origen: str  # "OPENAI" | "PLANTILLA"
    modelo: str | None = None


_PRINCIPIO_TXT = {
    PrincipioDua.REPRESENTACION: "ofrezca la información en más de un formato (texto, esquema, audio o imagen) y aclare el vocabulario",
    PrincipioDua.ACCION_EXPRESION: "permita que el estudiante demuestre lo que sabe de más de una manera y dé apoyos para planificar",
    PrincipioDua.PARTICIPACION: "dé opciones, anticipe lo que va a pasar y reduzca las fuentes de estrés para sostener el interés",
}
_BARRERA_TXT = {
    TipoBarrera.ACTITUDINAL: "creencias o actitudes del entorno que limitan la participación",
    TipoBarrera.COMUNICATIVA: "instrucciones o mensajes que no se entienden con claridad",
    TipoBarrera.PEDAGOGICA: "metodologías de enseñanza con pocas alternativas",
    TipoBarrera.EVALUATIVA: "formas de evaluar con poco margen de opción o de claridad",
    TipoBarrera.SENSORIAL: "estímulos del ambiente (ruido, luz, olores, multitudes) que dificultan concentrarse",
    TipoBarrera.SOCIAL: "dinámicas de grupo y de interacción que excluyen o aíslan",
    TipoBarrera.INSTITUCIONAL: "políticas o procedimientos que no contemplan distintas formas de participar",
    TipoBarrera.TECNOLOGICA: "herramientas o plataformas con poca accesibilidad",
}
_ESCENARIO_TXT = {
    Escenario.AULA: "el aula", Escenario.CAMPUS: "el campus", Escenario.VIRTUALIDAD: "los espacios virtuales",
    Escenario.LABORATORIOS: "los laboratorios", Escenario.PRACTICA_CLINICA: "las prácticas clínicas",
    Escenario.PRACTICA_SALUD_PUBLICA: "las prácticas de salud pública", Escenario.EVENTOS: "los eventos universitarios",
    Escenario.PASANTIAS: "las pasantías",
}


def template_text(p: AIPromptInput) -> str:
    """Texto accesible determinista (sin IA) en español claro."""
    return (
        f"Qué pasa: en {_ESCENARIO_TXT[p.escenario]} puede haber {_BARRERA_TXT[p.tipo_barrera]}.\n"
        f"Qué puede hacer usted como docente: {_PRINCIPIO_TXT[p.principio_dua]}.\n"
        "Cómo hacerlo: escriba las instrucciones en pasos cortos y concretos, avise con anticipación los cambios y "
        "ofrezca una segunda forma de participar o de entregar el trabajo.\n"
        "Esta medida es universal: ayuda a todo el grupo y no requiere conocer información personal de nadie."
    )


def _get_client() -> Any | None:
    """Cliente LangChain (`ChatOpenAI`) o None si no hay clave/librería. Las pruebas lo reemplazan por un espía."""
    s = get_settings()
    if not s.openai_api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except Exception:  # librería opcional no instalada
        return None
    return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0.3, timeout=20, max_retries=1)


def build_messages(p: AIPromptInput) -> list[tuple[str, str]]:
    payload = p.to_payload()
    assert tuple(payload) == CAMPOS_PERMITIDOS  # defensa en profundidad
    return [("system", SYSTEM_PROMPT), ("human", json.dumps(payload, ensure_ascii=False))]


def generate_accessible_text(prompt: AIPromptInput) -> AIResult:
    """Genera el «texto accesible» para docentes. Solo acepta `AIPromptInput`."""
    if not isinstance(prompt, AIPromptInput):
        raise AIPrivacyError("La IA solo acepta un AIPromptInput(tipo_barrera, escenario, principio_dua).")
    client = _get_client()
    if client is None:
        return AIResult(template_text(prompt), "PLANTILLA")
    try:
        resp = client.invoke(build_messages(prompt))
        texto = str(getattr(resp, "content", resp)).strip()
        if not texto:
            raise ValueError("respuesta vacía")
        return AIResult(texto, "OPENAI", get_settings().openai_model)
    except Exception:  # noqa: BLE001 - cualquier fallo externo degrada a plantilla
        logger.warning("Falló la llamada a OpenAI; se usa la plantilla determinista.")
        return AIResult(template_text(prompt), "PLANTILLA")
