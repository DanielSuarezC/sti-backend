"""Catálogo DUA semilla: CAST UDL Guidelines 2.2 (3 principios, 9 pautas, 31 puntos de verificación) y estrategias
institucionales etiquetadas por escenario (8) y tipo de barrera (8).

IMPORTANTE: es una PROPUESTA inicial redactada para el contexto universitario colombiano (Enfermería). Debe ser
revisada y validada por el equipo pedagógico (Bienestar/Inclusión) antes del piloto; el Administrador puede editarla
desde M1 sin tocar código. Fuente de los principios/pautas: CAST (2024), UDL Guidelines 2.2.
"""

from __future__ import annotations

FUENTE = "CAST (2024). Universal Design for Learning Guidelines 2.2 — adaptación institucional pendiente de validación pedagógica"

R, A, P = "REPRESENTACION", "ACCION_EXPRESION", "PARTICIPACION"

PRINCIPIOS = {
    R: "Proporcionar múltiples formas de representación (el QUÉ del aprendizaje)",
    A: "Proporcionar múltiples formas de acción y expresión (el CÓMO del aprendizaje)",
    P: "Proporcionar múltiples formas de implicación o participación (el POR QUÉ del aprendizaje)",
}

# pauta -> (principio, nombre, [(punto, texto)])
PAUTAS: dict[int, tuple[str, str, list[tuple[str, str]]]] = {
    1: (R, "Percepción", [
        ("1.1", "Ofrecer formas de personalizar la visualización de la información"),
        ("1.2", "Ofrecer alternativas para la información auditiva"),
        ("1.3", "Ofrecer alternativas para la información visual"),
    ]),
    2: (R, "Lenguaje y símbolos", [
        ("2.1", "Aclarar el vocabulario y los símbolos"),
        ("2.2", "Aclarar la sintaxis y la estructura"),
        ("2.3", "Apoyar la decodificación de textos, notación matemática y símbolos"),
        ("2.4", "Promover la comprensión entre diferentes idiomas"),
        ("2.5", "Ilustrar a través de múltiples medios"),
    ]),
    3: (R, "Construcción de conocimiento", [
        ("3.1", "Activar o proporcionar conocimientos previos"),
        ("3.2", "Resaltar patrones, características críticas, ideas principales y relaciones"),
        ("3.3", "Guiar el procesamiento y la visualización de la información"),
        ("3.4", "Maximizar la transferencia y la generalización"),
    ]),
    4: (A, "Interacción física", [
        ("4.1", "Variar los métodos de respuesta y navegación"),
        ("4.2", "Optimizar el acceso a herramientas y tecnologías de apoyo"),
    ]),
    5: (A, "Expresión y comunicación", [
        ("5.1", "Usar múltiples medios de comunicación"),
        ("5.2", "Usar múltiples herramientas para la construcción y la composición"),
        ("5.3", "Desarrollar fluidez con niveles graduados de apoyo para la práctica y el desempeño"),
    ]),
    6: (A, "Desarrollo de estrategias", [
        ("6.1", "Guiar el establecimiento adecuado de metas"),
        ("6.2", "Apoyar la planificación y el desarrollo de estrategias"),
        ("6.3", "Facilitar la gestión de información y recursos"),
        ("6.4", "Mejorar la capacidad de monitorear el progreso"),
    ]),
    7: (P, "Dar la bienvenida a intereses e identidades", [
        ("7.1", "Optimizar la elección individual y la autonomía"),
        ("7.2", "Optimizar la relevancia, el valor y la autenticidad"),
        ("7.3", "Minimizar las amenazas y las distracciones"),
    ]),
    8: (P, "Mantener el esfuerzo y la persistencia", [
        ("8.1", "Resaltar la relevancia de metas y objetivos"),
        ("8.2", "Variar las demandas y los recursos para optimizar el desafío"),
        ("8.3", "Fomentar la colaboración y la comunidad"),
        ("8.4", "Aumentar la retroalimentación orientada al dominio"),
    ]),
    9: (P, "Capacidad emocional", [
        ("9.1", "Promover expectativas y creencias que optimicen la motivación"),
        ("9.2", "Facilitar habilidades y estrategias personales de afrontamiento"),
        ("9.3", "Desarrollar la autoevaluación y la reflexión"),
    ]),
}

assert sum(len(v[2]) for v in PAUTAS.values()) == 31  # 31 puntos de verificación

AULA, CAMPUS, VIRT, LAB = "AULA", "CAMPUS", "VIRTUALIDAD", "LABORATORIOS"
PCLI, PSP, EVE, PAS = "PRACTICA_CLINICA", "PRACTICA_SALUD_PUBLICA", "EVENTOS", "PASANTIAS"
ACT, COM, PED, EVA, SEN, SOC, INS, TEC = (
    "ACTITUDINAL", "COMUNICATIVA", "PEDAGOGICA", "EVALUATIVA", "SENSORIAL", "SOCIAL", "INSTITUCIONAL", "TECNOLOGICA",
)

# (principio, pauta, punto, nombre, descripcion, escenarios, tipos_barrera, perfil)
_ESTRATEGIAS: list[tuple] = [
    (R, 1, "1.1", "Materiales en formatos personalizables",
     "Entregar diapositivas, guías y lecturas en formatos digitales editables (PDF accesible o documento) que permitan "
     "ajustar tamaño de letra, contraste, espaciado e interlineado, sin recargar visualmente la página.",
     [AULA, VIRT, LAB], [SEN, TEC, PED], "Estudiantes con sensibilidad visual o que se sobrecargan con diseños densos."),
    (R, 1, "1.2", "Subtítulos, transcripciones y avisos visuales",
     "Activar subtítulos y entregar transcripción de clases, videos y audios; acompañar los avisos sonoros "
     "(timbres, alarmas, anuncios) con una señal visual o un aviso previo por escrito.",
     [VIRT, AULA, EVE], [SEN, COM], "Estudiantes con hipersensibilidad auditiva o dificultad para procesar el habla rápida."),
    (R, 1, "1.3", "Descripción textual de imágenes y diagramas",
     "Acompañar esquemas anatómicos, fotografías clínicas y gráficos con una descripción escrita paso a paso de lo "
     "que se debe observar.",
     [LAB, AULA], [SEN, PED], "Estudiantes que se apoyan en el lenguaje literal y explícito."),
    (R, 2, "2.1", "Glosario de términos clínicos y lenguaje literal",
     "Entregar antes de cada unidad un glosario de términos clínicos y evitar o explicar modismos, ironías y lenguaje "
     "figurado en clase y en las evaluaciones.",
     [AULA, PCLI], [COM, PED], "Estudiantes con interpretación literal del lenguaje."),
    (R, 2, "2.2", "Instrucciones paso a paso, literales y sin ambigüedad",
     "Redactar las instrucciones de actividades, laboratorios y prácticas como listas numeradas, con un solo paso por "
     "línea, criterios explícitos y ejemplos de producto terminado.",
     [AULA, LAB, PCLI, PSP], [COM, EVA, PED], "Estudiantes que necesitan estructura explícita y secuencias claras."),
    (R, 2, "2.3", "Texto compatible con lector de pantalla",
     "Publicar los materiales en formatos compatibles con lectores de pantalla y herramientas de lectura en voz alta, "
     "con encabezados y estructura lógica.",
     [AULA, VIRT], [TEC, SEN], "Estudiantes que usan apoyos de lectura o decodificación."),
    (R, 2, "2.5", "Conceptos con múltiples medios",
     "Explicar los contenidos centrales con más de un medio: esquema, video corto, simulación o demostración, y no "
     "solo exposición oral.",
     [AULA, LAB, VIRT], [PED], "Estudiantes con perfil visual o que aprenden mejor con ejemplos concretos."),
    (R, 3, "3.1", "Agenda y resumen previo de la sesión",
     "Compartir antes de cada clase la agenda, los objetivos y un resumen de lo anterior para activar conocimientos "
     "previos y anticipar lo que va a ocurrir.",
     [AULA, VIRT], [PED, COM], "Estudiantes que se benefician de la anticipación y la previsibilidad."),
    (R, 3, "3.2", "Organizadores gráficos y mapas conceptuales",
     "Resaltar ideas principales, relaciones y patrones con mapas conceptuales, tablas comparativas y códigos de "
     "color consistentes.",
     [AULA], [PED], "Estudiantes con atención al detalle que necesitan ver el panorama general."),
    (R, 3, "3.3", "Información en fragmentos con tiempo de procesamiento",
     "Presentar la información en bloques cortos, con pausas y tiempo explícito para procesar antes de pedir "
     "respuestas o pasar al siguiente tema.",
     [AULA, VIRT, PCLI], [PED, EVA], "Estudiantes con procesamiento más lento en situaciones de alta demanda."),
    (R, 3, "3.4", "Casos clínicos graduados para generalizar",
     "Usar casos y escenarios que varíen gradualmente (del caso simple al complejo) para facilitar la transferencia "
     "a situaciones reales de práctica.",
     [PCLI, LAB, PAS], [PED, INS], "Estudiantes que requieren apoyo explícito para generalizar aprendizajes."),
    (A, 4, "4.1", "Varias formas de responder y participar",
     "Permitir responder de forma oral, escrita, digital o con esquemas, y participar por foro, chat o al final de la "
     "clase en lugar de solo en vivo.",
     [AULA, VIRT], [EVA, COM], "Estudiantes con dificultad para la respuesta oral espontánea."),
    (A, 4, "4.2", "Acceso anticipado a tecnologías de apoyo",
     "Garantizar y probar con anticipación el software, los dispositivos y las plataformas de apoyo que usa el "
     "estudiante, con soporte técnico disponible.",
     [LAB, AULA, VIRT], [TEC, INS], "Estudiantes que usan tecnología asistiva."),
    (A, 5, "5.1", "Medios alternos para entregar y expresar",
     "Aceptar productos en formatos alternos (informe escrito, presentación grabada, infografía) cuando se evalúa el "
     "mismo resultado de aprendizaje.",
     [AULA, VIRT], [EVA, COM], "Estudiantes con dificultades en la exposición oral o la escritura extensa."),
    (A, 5, "5.2", "Plantillas y herramientas de composición",
     "Dar plantillas, formatos guiados y ejemplos para informes, notas de enfermería y trabajos escritos.",
     [AULA, PCLI], [PED, COM], "Estudiantes que se benefician de estructuras predefinidas."),
    (A, 5, "5.3", "Práctica graduada con apoyos decrecientes",
     "Planear la progresión simulación, laboratorio y práctica supervisada, con apoyos que disminuyen según el "
     "dominio demostrado.",
     [LAB, PCLI, PAS], [PED, ACT], "Estudiantes que necesitan entrenamiento previo en procedimientos nuevos."),
    (A, 6, "6.1", "Metas semanales y listas de verificación",
     "Acordar metas pequeñas y medibles por semana y entregar listas de verificación para tareas y entregas.",
     [AULA, PAS], [PED, INS], "Estudiantes con dificultades de funciones ejecutivas."),
    (A, 6, "6.2", "Cronograma visual y rutinas predecibles",
     "Entregar un cronograma visual con los cortes C1, C2 y C3, y los horarios, sitios y rutas de las prácticas "
     "informados con anticipación.",
     [AULA, PCLI, PSP, PAS], [PED, INS], "Estudiantes que requieren rutinas estables y avisos de cambios."),
    (A, 6, "6.3", "Carpeta organizada y lista de materiales",
     "Mantener un único espacio organizado con materiales y una lista del instrumental o los recursos que se necesitan "
     "en cada sesión.",
     [LAB, VIRT], [PED, TEC], "Estudiantes que se desorganizan con múltiples fuentes de información."),
    (A, 6, "6.4", "Rúbricas claras y retroalimentación frecuente",
     "Compartir rúbricas antes de las evaluaciones y dar retroalimentación frecuente con indicadores de avance.",
     [AULA, PCLI], [EVA], "Estudiantes que necesitan criterios explícitos."),
    (P, 7, "7.1", "Opciones y autonomía en trabajos",
     "Ofrecer elegir tema, formato o rol dentro de los trabajos y las actividades de grupo.",
     [AULA, EVE], [SOC, ACT, PED], "Estudiantes con intereses especiales o preferencias marcadas."),
    (P, 7, "7.2", "Relevancia vinculada a intereses",
     "Conectar las tareas con los intereses y fortalezas del estudiante y con su proyección académica y laboral.",
     [AULA, PAS], [PED], "Estudiantes con intereses intensos que sostienen la motivación."),
    (P, 7, "7.3", "Espacios de baja estimulación y control sensorial",
     "Disponer espacios tranquilos, ubicaciones con menos ruido y luz, y permitir elementos sensoriales (audífonos, "
     "gafas) durante clases y evaluaciones.",
     [CAMPUS, AULA, LAB, EVE], [SEN, INS], "Estudiantes con hipersensibilidad sensorial."),
    (P, 7, "7.3", "Aviso previo de cambios y programa de eventos detallado",
     "Avisar con anticipación cambios de salón, horario o actividad y compartir el programa detallado de eventos "
     "(duración, aforo, ruido esperado y salidas).",
     [EVE, CAMPUS, AULA], [SEN, COM, INS], "Estudiantes que se desorganizan ante cambios imprevistos."),
    (P, 7, "7.3", "Evaluación en ambiente de baja estimulación",
     "Ofrecer presentar parciales y exámenes en un espacio con poco ruido y distracciones, con las instrucciones "
     "entregadas por escrito.",
     [AULA], [EVA, SEN], "Estudiantes que se bloquean con ruido y entorno concurrido."),
    (P, 8, "8.1", "Objetivos visibles al inicio y cierre de cada sesión",
     "Presentar el objetivo de la sesión al comenzar y recapitular al cerrar, de modo que el estudiante sepa qué se espera.",
     [AULA, VIRT], [COM, PED], "Estudiantes que necesitan claridad sobre el propósito de la actividad."),
    (P, 8, "8.2", "Demandas flexibles y tiempo ajustable",
     "Variar la dificultad y ofrecer tiempo adicional o descansos programados en tareas y evaluaciones.",
     [AULA], [EVA, PED], "Estudiantes con fatiga por sobrecarga o procesamiento más lento."),
    (P, 8, "8.3", "Trabajo colaborativo con roles definidos y tutoría entre pares",
     "Estructurar los grupos con roles claros, instrucciones de interacción y tutoría entre pares voluntaria.",
     [AULA, LAB, PCLI, PSP], [SOC, ACT], "Estudiantes con dificultades en la interacción social espontánea."),
    (P, 8, "8.4", "Retroalimentación específica centrada en fortalezas",
     "Dar retroalimentación concreta, inmediata y centrada en lo que se logró y en cómo mejorar.",
     [AULA, PCLI], [EVA, ACT], "Estudiantes sensibles a la crítica ambigua."),
    (P, 9, "9.1", "Lenguaje de capacidades y formación en neurodiversidad",
     "Promover un trato basado en capacidades y ofrecer formación breve a docentes y compañeros sobre neurodiversidad "
     "para reducir estigma y malentendidos.",
     [AULA, CAMPUS, PCLI], [ACT, SOC, INS], "Estudiantes expuestos a prejuicios o falta de conocimiento del entorno."),
    (P, 9, "9.2", "Pausa acordada y plan de regulación sensorial",
     "Acordar una señal discreta (tarjeta de pausa) para salir a regularse sin perder la participación y definir un "
     "plan de regulación para prácticas y eventos.",
     [AULA, LAB, PCLI, EVE], [SEN, SOC], "Estudiantes con sobrecarga sensorial o emocional en situaciones de alta demanda."),
    (P, 9, "9.3", "Bitácora de aprendizaje y autoevaluación",
     "Usar bitácoras y autoevaluación con rúbrica para reflexionar sobre lo aprendido y sobre qué apoyos funcionan.",
     [AULA, PAS], [PED, EVA], "Estudiantes que fortalecen su autodeterminación y autoconocimiento."),
    (P, 7, "7.3", "Preparación previa de salidas de campo",
     "Entregar con anticipación el guion de la salida de campo: rutas, roles, personas de contacto, posibles imprevistos "
     "y plan alterno, y reconocer el lugar antes cuando sea posible.",
     [PSP], [SOC, COM, INS], "Estudiantes que requieren previsibilidad en entornos comunitarios."),
    (A, 6, "6.2", "Acuerdo de ajustes con instituciones de práctica y pasantía",
     "Gestionar con anticipación, y con consentimiento del estudiante, los ajustes necesarios con la institución de "
     "práctica o pasantía: turnos, tutor de referencia y espacios de pausa.",
     [PCLI, PSP, PAS], [INS, ACT], "Estudiantes que inician escenarios externos fuera del campus."),
]

CODIGO_PRINCIPIO = {R: "R", A: "A", P: "P"}


def build_catalog() -> list[dict]:
    """Lista de dicts lista para insertar en ESTRATEGIA_DUA_CATALOGO."""
    out = []
    contador: dict[str, int] = {}
    for principio, pauta, punto, nombre, desc, escenarios, tipos, perfil in _ESTRATEGIAS:
        pref = f"DUA-{CODIGO_PRINCIPIO[principio]}-{punto}"
        contador[pref] = contador.get(pref, 0) + 1
        out.append({
            "codigo": f"{pref}-{contador[pref]:02d}",
            "nombre": nombre,
            "descripcion_pedagogica": desc,
            "principio": principio,
            "pauta": pauta,
            "pauta_nombre": PAUTAS[pauta][1],
            "punto_verificacion": punto,
            "escenarios": escenarios,
            "tipos_barrera": tipos,
            "perfil_estudiante": perfil,
            "fuente": FUENTE,
            "activo": True,
        })
    return out


assert len(_ESTRATEGIAS) >= 30
