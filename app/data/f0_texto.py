"""Texto del Formato F0 (consentimiento informado), versionado y en lenguaje claro (arquitectura v7 §4.3, HU-05/HU-18).

REVISIÓN JURÍDICA PENDIENTE: el texto es una propuesta redactada para el piloto con base en la Ley 1581 de 2012,
el Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015) y la Ley Estatutaria 1618 de 2013. Debe ser revisado y
aprobado por la oficina jurídica y de protección de datos de la Universidad de Córdoba ANTES del piloto con
estudiantes reales. Si se cambia una sola palabra, se debe subir `VERSION` (el hash cambia solo y las firmas ya
hechas conservan la versión que firmaron).

El hash SHA-256 se calcula sobre `texto_canonico()`: título + secciones + aceptaciones, en ese orden.
"""

from __future__ import annotations

import hashlib

VERSION = "F0-v1"
TITULO = "Consentimiento informado para participar en el Sistema Tutor Inteligente (STI)"
REVISION_JURIDICA_PENDIENTE = True
AVISO_REVISION = (
    "Texto en revisión jurídica: no usar con estudiantes reales hasta que la oficina jurídica y de protección de "
    "datos de la Universidad lo apruebe."
)

#: Secciones en lenguaje claro: (id, titulo, [parrafos])
SECCIONES: list[tuple[str, str, list[str]]] = [
    (
        "proposito",
        "Para qué sirve el STI",
        [
            "El Sistema Tutor Inteligente (STI) de la Universidad de Córdoba ayuda a Bienestar Universitario a conocer "
            "cómo aprende usted y qué apoyos le sirven, para construir con usted un Plan MAAR-TEA: un documento con "
            "los ajustes y apoyos que la universidad se compromete a ofrecerle.",
            "El STI no es un diagnóstico ni una evaluación clínica. Las barreras que se identifican son del entorno "
            "(la clase, el campus, los procesos), no de usted.",
        ],
    ),
    (
        "datos",
        "Qué datos se recogen",
        [
            "Datos de identificación: nombre, código estudiantil, programa y correo institucional.",
            "Un cuestionario de tamizaje (AQ-10) con sus respuestas y su puntaje. Es una herramienta de orientación, "
            "no un diagnóstico.",
            "Información que usted y Bienestar escriben juntos: cómo se comunica, qué le molesta o le ayuda en lo "
            "sensorial, qué tareas hace de forma autónoma, sus fortalezas, intereses y metas.",
            "El contexto de sus clases y las barreras y facilitadores que usted encuentra en la universidad.",
            "Parte de esta información es un dato sensible relacionado con su salud. La ley exige su autorización "
            "expresa para tratarla, y usted puede negarse.",
        ],
    ),
    (
        "quien_accede",
        "Quién puede ver su información",
        [
            "Bienestar Universitario (profesionales del equipo de inclusión): puede ver y trabajar con toda su información.",
            "Coordinación de su programa: puede leer su caracterización, el contexto, las barreras y su Plan, y validarlo.",
            "Docentes: solo ven los ajustes y estrategias que les corresponden en sus asignaturas, escritos para que "
            "puedan aplicarlos. Nunca ven su cuestionario AQ-10, ni su caracterización, ni diagnósticos.",
            "Familiares: solo si usted lo autoriza, y solo lo que usted decida (por ejemplo, el Plan). Puede quitar "
            "ese permiso cuando quiera.",
            "El personal técnico del sistema no usa sus datos para otros fines. Cada vez que alguien consulta datos "
            "sensibles queda un registro de auditoría.",
        ],
    ),
    (
        "proteccion",
        "Cómo protegemos sus datos",
        [
            "Sus respuestas del AQ-10, sus narrativas y los datos sensoriales y de comunicación se guardan cifrados.",
            "El sistema registra quién consulta y quién modifica datos sensibles.",
            "El puntaje del AQ-10, su nombre, su diagnóstico o cualquier dato que lo identifique nunca se envían a "
            "servicios de inteligencia artificial externos. Si se usa IA para redactar textos de apoyo para docentes, "
            "solo recibe el tipo de barrera, el escenario y el principio de diseño universal, sin datos personales.",
            "Sus datos no se venden ni se usan para publicidad. Los informes institucionales son agregados y no "
            "permiten identificarlo.",
        ],
    ),
    (
        "derechos",
        "Sus derechos (Ley 1581 de 2012)",
        [
            "Acceso: puede conocer y descargar los datos que tenemos sobre usted.",
            "Rectificación: puede pedir que corrijamos datos incorrectos o incompletos.",
            "Cancelación (supresión): puede pedir que eliminemos sus datos cuando no sean necesarios o haya retirado su consentimiento.",
            "Oposición: puede oponerse a un uso específico de sus datos.",
            "Puede ejercer estos derechos desde el STI, en la sección «Mis derechos». Respondemos dentro de los plazos "
            "legales: 10 días hábiles para consultas y 15 días hábiles para reclamos.",
        ],
    ),
    (
        "retiro",
        "Puede retirar su consentimiento cuando quiera",
        [
            "Usted puede retirar este consentimiento en cualquier momento, sin explicar por qué.",
            "Retirarlo no tiene ninguna consecuencia académica: no afecta sus notas, su matrícula ni su permanencia.",
            "Si lo retira, su cuenta se inactiva, sus datos se archivan y dejan de usarse, según la Ley 1581 de 2012, "
            "y Bienestar recibe un aviso para acompañarlo si usted lo desea.",
        ],
    ),
    (
        "responsable",
        "Quién es responsable del tratamiento",
        [
            "Universidad de Córdoba, a través de Bienestar Universitario. Para consultas o reclamos sobre sus datos, "
            "use la sección «Mis derechos» del STI o los canales oficiales de Bienestar Universitario.",
        ],
    ),
]

#: Aceptaciones explícitas y separadas (cada una es una casilla distinta en la pantalla de firma).
ACEPTACIONES: list[dict] = [
    {
        "clave": "acepta_tratamiento_general",
        "obligatoria": True,
        "texto": "Entiendo para qué sirve el STI y autorizo el tratamiento de mis datos personales como se explica en este documento.",
    },
    {
        "clave": "acepta_datos_sensibles_salud",
        "obligatoria": True,
        "texto": (
            "Autorizo de forma expresa el tratamiento de mis datos sensibles relacionados con la salud (como el "
            "cuestionario AQ-10 y mi caracterización). Sé que puedo negarme y que puedo retirar esta autorización."
        ),
    },
    {
        "clave": "acepta_compartir_ajustes_docentes",
        "obligatoria": False,
        "texto": (
            "Autorizo que mis docentes reciban únicamente los ajustes y estrategias que les corresponden, sin mi "
            "caracterización ni mi cuestionario AQ-10. Si no lo autorizo, Bienestar coordinará con mis docentes de otra manera."
        ),
    },
]


def texto_canonico() -> str:
    partes = [VERSION, TITULO]
    for sid, titulo, parrafos in SECCIONES:
        partes.append(f"## {sid}: {titulo}")
        partes.extend(parrafos)
    for a in ACEPTACIONES:
        partes.append(f"[{a['clave']}] {a['texto']}")
    return "\n".join(partes)


def texto_hash() -> str:
    return hashlib.sha256(texto_canonico().encode("utf-8")).hexdigest()


def texto_plano_correo() -> str:
    """Versión en texto plano para la copia por correo (HU-18)."""
    out = [TITULO.upper(), ""]
    for _sid, titulo, parrafos in SECCIONES:
        out.append(titulo.upper())
        out.extend(f"- {p}" for p in parrafos)
        out.append("")
    return "\n".join(out)


def as_dict() -> dict:
    return {
        "version_texto": VERSION,
        "titulo": TITULO,
        "texto_hash": texto_hash(),
        "revision_juridica_pendiente": REVISION_JURIDICA_PENDIENTE,
        "aviso_revision": AVISO_REVISION if REVISION_JURIDICA_PENDIENTE else None,
        "secciones": [{"id": sid, "titulo": t, "parrafos": list(p)} for sid, t, p in SECCIONES],
        "aceptaciones": [dict(a) for a in ACEPTACIONES],
        "normativa": ["Ley 1581 de 2012", "Decreto 1377 de 2013 (Decreto 1074 de 2015)", "Ley Estatutaria 1618 de 2013"],
    }
