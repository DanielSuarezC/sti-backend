"""AQ-10 (adultos) de Allison, Auyeung y Baron-Cohen (2012), versión en español para el contexto colombiano.

REVISIÓN LINGÜÍSTICA PENDIENTE del equipo pedagógico (arquitectura v7 §5.2): se puede ajustar la redacción sin
modificar la lógica de puntuación validada. Puntúan 1 punto: ítems 1, 7, 8 y 10 respondidos "de acuerdo"
(totalmente o ligeramente) e ítems 2, 3, 4, 5, 6 y 9 respondidos "en desacuerdo". Punto de corte: >= 6.
Es un instrumento de TAMIZAJE, no de diagnóstico.
"""

from __future__ import annotations

FUENTE = (
    "Allison, C., Auyeung, B. & Baron-Cohen, S. (2012). Toward brief 'Red Flags' for autism screening: the "
    "Short Autism Spectrum Quotient and the Short Quantitative Checklist in 1,000 cases and 3,000 controls. "
    "J. Am. Acad. Child Adolesc. Psychiatry, 51(2), 202-212. Versión en español: adaptación institucional "
    "pendiente de revisión lingüística."
)

# (numero, texto, puntua_si)  puntua_si: ACUERDO | DESACUERDO
ITEMS = [
    (1, "A menudo noto pequeños sonidos que los demás no notan.", "ACUERDO"),
    (2, "Por lo general me concentro más en el panorama completo que en los pequeños detalles.", "DESACUERDO"),
    (3, "Me resulta fácil hacer más de una cosa a la vez.", "DESACUERDO"),
    (4, "Si hay una interrupción, puedo volver muy rápido a lo que estaba haciendo.", "DESACUERDO"),
    (5, "Me resulta fácil «leer entre líneas» cuando alguien me habla.", "DESACUERDO"),
    (6, "Sé cómo darme cuenta de si la persona que me escucha se está aburriendo.", "DESACUERDO"),
    (7, "Cuando leo un cuento me resulta difícil descubrir las intenciones de los personajes.", "ACUERDO"),
    (8, "Me gusta reunir información sobre categorías de cosas (por ejemplo, tipos de carro, de ave, de tren, de planta).", "ACUERDO"),
    (9, "Me resulta fácil darme cuenta de lo que otra persona piensa o siente con solo mirarle la cara.", "DESACUERDO"),
    (10, "Me resulta difícil descubrir las intenciones de las personas.", "ACUERDO"),
]

# Escala Likert de 4 puntos; `direccion` indica de qué lado de la escala cae la respuesta.
OPCIONES = [
    (1, "Totalmente de acuerdo", "ACUERDO"),
    (2, "Ligeramente de acuerdo", "ACUERDO"),
    (3, "Ligeramente en desacuerdo", "DESACUERDO"),
    (4, "Totalmente en desacuerdo", "DESACUERDO"),
]

PUNTO_CORTE = 6


def items_json() -> list[dict]:
    return [{"numero": n, "texto": t, "puntua_si": p} for n, t, p in ITEMS]


def opciones_json() -> list[dict]:
    return [{"valor": v, "etiqueta": e, "direccion": d} for v, e, d in OPCIONES]
