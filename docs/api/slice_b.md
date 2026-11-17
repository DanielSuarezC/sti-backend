# API del slice B: F0, ARCO, AQ-10, F1–F5 y motor DUA

Prefijo de todas las rutas: `/api/v1`. Autenticación `Authorization: Bearer <jwt>` (ver `auth.md`).
Errores: `{"detail": "<español>", "code": "SNAKE_CASE"}`; los 422 de validación agregan `errores: [{campo, mensaje}]`.
Todo texto de la API está en español colombiano. Lenguaje del sistema: **la barrera es del entorno, no de la persona**; el AQ-10 es **tamizaje, no diagnóstico**.

Convenciones del slice:

* Ningún `DELETE` borra físicamente: archiva (soft delete) y exige `motivo` (query `?motivo=`, 3–500 caracteres).
* Lectura de datos sensibles (AQ-10, F1, F2) queda en `LOG_AUDITORIA` (`ACCESO_AQ10`, `ACCESO_CARACTERIZACION`, `ACCESO_PERFIL_FORTALEZAS`).
* El estudiante necesita F0 firmado para todo, **excepto** `/consentimiento/*` y `/arco/*`. Sin F0 recibe `403 CONSENTIMIENTO_REQUERIDO` → redirigir a F0.
* Un estudiante solo ve/usa su propio `estudiante_id`; Bienestar el de los estudiantes de su alcance; Coordinador solo los de su programa; Docente **nunca** ve AQ-10, F1, F2, F3, F4, F5 ni sugerencias.
* Los `id` de estudiante en las rutas son `estudiante.id` (no `usuario.id`). El estudiante lo obtiene de `/estudiantes/...` (slice C2) o de su perfil.
* Si un rol no está en la lista de un endpoint recibe `403 ROL_NO_PERMITIDO` (rol equivocado) o `403 ACCESO_DENEGADO` (sin alcance sobre ese estudiante).

## Enums (valores permitidos)

| Enum | Valores |
|---|---|
| `Escenario` | `AULA`, `CAMPUS`, `VIRTUALIDAD`, `LABORATORIOS`, `PRACTICA_CLINICA`, `PRACTICA_SALUD_PUBLICA`, `EVENTOS`, `PASANTIAS` |
| `TipoBarrera` | `ACTITUDINAL`, `COMUNICATIVA`, `PEDAGOGICA`, `EVALUATIVA`, `SENSORIAL`, `SOCIAL`, `INSTITUCIONAL`, `TECNOLOGICA` |
| `EstadoBarrera` | `IDENTIFICADA`, `PERSISTENTE`, `SUPERADA` |
| `Frecuencia` | `OCASIONAL`, `FRECUENTE`, `CONSTANTE` |
| `Severidad` | `LEVE`, `MODERADA`, `SEVERA` |
| `OrigenPercibido` | `ESTUDIANTE`, `CONTEXTO`, `INTERACCION` |
| `TipoFacilitador` | `PERSONAL`, `PEDAGOGICO`, `SOCIAL`, `INSTITUCIONAL`, `TECNOLOGICO` |
| `IntensidadFacilitador` | `LEVE`, `MODERADA`, `SIGNIFICATIVA` |
| `Renovabilidad` | `FIJO`, `VARIABLE`, `TEMPORAL` |
| `PrincipioDua` | `REPRESENTACION`, `ACCION_EXPRESION`, `PARTICIPACION` |
| `EstadoSugerencia` | `PROPUESTA`, `ACEPTADA`, `MODIFICADA`, `RECHAZADA` |
| `OrigenSugerencia` | `CBR`, `FILTRO_CATALOGO`, `MANUAL` |
| `EstadoFormato` (F1/F2) | `INCOMPLETA`, `EN_REVISION`, `COMPLETA` |
| `TipoSensorial` | `AUDITIVA`, `VISUAL`, `TACTIL`, `OLFATIVA`, `GUSTATIVA`, `VESTIBULAR`, `PROPIOCEPCION` |
| `NivelAutonomia` | `BAJA`, `MEDIA`, `ALTA` |
| `NivelBMAC` (prioridad de preferencia) | `BAJA`, `MEDIA`, `ALTA`, `CRITICA` |
| `NivelBMA` | `BAJA`, `MEDIA`, `ALTA` |
| `NivelConsolidacion` | `EMERGENTE`, `EN_DESARROLLO`, `CONSOLIDADA` |
| `IntensidadInteres` | `LEVE`, `MODERADO`, `INTENSO`, `OBSESIVO` |
| `TipoEstrategiaAprendizaje` | `VISUAL`, `AUDITIVA`, `CINESTESICA`, `LECTOESCRITURA`, `ESTRUCTURACION`, `RUTINA`, `OTRA` |
| `TipoMeta` | `ACADEMICA`, `PROFESIONAL`, `PERSONAL` |
| `ModalidadFirma` | `AUTONOMA`, `ASISTIDA_BIENESTAR` |
| `TipoArco` | `ACCESO`, `RECTIFICACION`, `CANCELACION`, `OPOSICION` |
| `EstadoArco` | `RECIBIDA`, `EN_TRAMITE`, `RESUELTA`, `RECHAZADA` |
| `ModalidadAQ10` | `ASISTIDA`, `AUTOAPLICADA` |

---

# 1. F0 — Consentimiento informado (RF-05/06/07, HU-05/HU-18)

Texto en `app/data/f0_texto.py`. **Revisión jurídica pendiente** (se informa en `revision_juridica_pendiente`): mostrar el aviso `aviso_revision` a quien opera el piloto; no usar con estudiantes reales hasta que la oficina jurídica lo apruebe.

### `GET /consentimiento/texto` — público (sin token)

Respuesta `200`:

```json
{
  "version_texto": "F0-v1",
  "titulo": "Consentimiento informado para participar en el Sistema Tutor Inteligente (STI)",
  "texto_hash": "9f2c…(SHA-256 de 64 hex)",
  "revision_juridica_pendiente": true,
  "aviso_revision": "Texto en revisión jurídica: …",
  "secciones": [{"id": "proposito", "titulo": "Para qué sirve el STI", "parrafos": ["…"]}],
  "aceptaciones": [
    {"clave": "acepta_tratamiento_general", "obligatoria": true, "texto": "…"},
    {"clave": "acepta_datos_sensibles_salud", "obligatoria": true, "texto": "…"},
    {"clave": "acepta_compartir_ajustes_docentes", "obligatoria": false, "texto": "…"}
  ],
  "normativa": ["Ley 1581 de 2012", "Decreto 1377 de 2013 (Decreto 1074 de 2015)", "Ley Estatutaria 1618 de 2013"]
}
```

Secciones (`id`): `proposito`, `datos`, `quien_accede`, `proteccion`, `derechos`, `retiro`, `responsable`. Cada aceptación es **una casilla separada** en la pantalla de firma.

### `GET /consentimiento/mio` — ESTUDIANTE (no exige F0)

`200` (sin firmar: `estado:"PENDIENTE"` y el resto `null`):

```json
{"estudiante_id": 7, "estado": "FIRMADO", "firmado": true, "version_vigente": "F0-v1", "version_firmada": "F0-v1",
 "texto_desactualizado": false, "firmado_at": "2026-11-16T15:04:05+00:00", "nombre_firmante": "Ana Lopez Perez",
 "modalidad": "AUTONOMA", "acepta_tratamiento_general": true, "acepta_datos_sensibles_salud": true,
 "acepta_compartir_ajustes_docentes": true, "copia_enviada_at": "2026-11-16T15:04:05+00:00", "revocado_at": null,
 "firma_hash": "…", "texto_hash": "…"}
```

`estado`: `PENDIENTE | FIRMADO | REVOCADO`.

### `POST /consentimiento/firmar` — ESTUDIANTE o BIENESTAR (firma asistida) — `201`

Cuerpo:

```json
{"version_texto": "F0-v1", "texto_hash": "<el de GET /consentimiento/texto>", "nombre_firmante": "Ana Lopez Perez",
 "acepta_tratamiento_general": true, "acepta_datos_sensibles_salud": true, "acepta_compartir_ajustes_docentes": true,
 "estudiante_id": null}
```

* `estudiante_id`: **solo** Bienestar (modalidad asistida: el estudiante teclea su nombre en el equipo del profesional); el estudiante no debe enviarlo (`403`).
* `nombre_firmante`: nombre tecleado; debe corresponder al de la cuenta (todas sus palabras están en el nombre de la cuenta; mínimo 2; sin tildes/mayúsculas ni orden).
* `acepta_tratamiento_general` y `acepta_datos_sensibles_salud` deben ser `true`. `acepta_compartir_ajustes_docentes` puede ser `false` (si es falso, los docentes no reciben ajustes por el sistema; Bienestar coordina de otra forma).

Efecto: crea el registro **inmutable** en `CONSENTIMIENTO` (+ detalle), sello de tiempo del servidor, IP y user-agent, hash SHA-256 del texto y de la firma; pasa la cuenta de `PENDIENTE_CONSENTIMIENTO` a `ACTIVO`; envía copia por correo (evento `CONSENTIMIENTO_COPIA`); audita `CONSENTIMIENTO_FIRMADO`. Respuesta: el mismo objeto de `GET /consentimiento/mio` + `"detail"` (para Bienestar incluye también `asistido_por_id` y `motivo_revocacion`).

Errores: `409 CONSENTIMIENTO_YA_FIRMADO`, `409 CONSENTIMIENTO_REVOCADO` (la cuenta debe reactivarla un administrador), `409 TEXTO_DESACTUALIZADO` (volver a leer; trae `version_vigente`), `422 ACEPTACION_REQUERIDA`, `422 NOMBRE_NO_COINCIDE`, `422 ESTUDIANTE_REQUERIDO` (Bienestar sin `estudiante_id`), `403 CUENTA_INACTIVA`.

### `POST /consentimiento/revocar` — ESTUDIANTE (RF-07)

Cuerpo: `{"confirmar": true, "motivo": "opcional, no está obligado a explicar"}`. `confirmar` debe ser `true` (`422 CONFIRMACION_REQUERIDA`).

Efecto: consentimiento `REVOCADO`; cuenta `INACTIVO` (el token deja de servir: `403 CUENTA_INACTIVA`); sesiones revocadas; autorizaciones de familiares revocadas; **soft delete** de todos los datos del estudiante en el STI (AQ-10, F1–F5, sugerencias, plan y sus hijos, notas, exportaciones…). Se **conservan**: la cuenta, los consentimientos, las solicitudes ARCO, el log de auditoría, y los registros académicos institucionales (`matricula`, `registro_inasistencia`). Los casos CBR (anónimos) permanecen sin vínculo al plan. Notifica a Bienestar (evento `CONSENTIMIENTO_REVOCADO`, push + correo) y audita `CONSENTIMIENTO_REVOCADO`.

`200`: `{"estado": "REVOCADO", "revocado_at": "…", "datos_archivados": {"respuesta_aq10": 1, "caracterizacion": 1, …}, "detail": "…"}`. Error: `409 SIN_CONSENTIMIENTO_VIGENTE`.

### `GET /consentimiento/{estudiante_id}` — BIENESTAR, ADMIN

Estado del F0 de un estudiante (objeto como `mio` + `asistido_por_id`, `motivo_revocacion`). Otros roles: `403`.

---

# 2. Derechos ARCO (RNF-07, Ley 1581/2012)

Plazos legales (días hábiles, lunes a viernes, **sin descontar festivos**): `ACCESO` = consulta, 10 días (prórroga 5); `RECTIFICACION`, `CANCELACION`, `OPOSICION` = reclamo, 15 días (prórroga 8). Una sola prórroga. Estos endpoints **no** exigen F0.

Objeto `SolicitudArco`:

```json
{"id": 3, "radicado": "ARCO-2026-000003", "estudiante_id": 7, "tipo": "ACCESO", "tramite": "CONSULTA",
 "descripcion": "Quiero conocer mis datos.", "estado": "RECIBIDA", "fecha_radicacion": "2026-11-16",
 "fecha_limite": "2026-11-30", "prorrogada": false, "motivo_prorroga": null, "dias_para_vencer": 14, "vencida": false,
 "respuesta": null, "atendida_at": null, "solicitante_id": 12, "atendida_por_id": null}
```

(`solicitante_id` y `atendida_por_id` solo los ve el personal; el estudiante no los recibe.)

| Método y ruta | Roles | Cuerpo | Respuesta / errores |
|---|---|---|---|
| `POST /arco/solicitudes` | ESTUDIANTE | `{"tipo": TipoArco, "descripcion": "10–4000 caracteres"}` | `201 SolicitudArco`. Notifica a Bienestar (push + correo). `422 DESCRIPCION_MUY_CORTA` |
| `GET /arco/mis-solicitudes` | ESTUDIANTE | — | `{items: [SolicitudArco], total}` |
| `GET /arco/exportar-mis-datos` | ESTUDIANTE | — | `200` JSON descargable (`Content-Disposition: attachment; filename="mis-datos-sti-AAAA-MM-DD.json"`) con los datos propios **descifrados**: `{generado_at, aviso, cuenta, estudiante, consentimientos, solicitudes_arco, datos: {<tabla>: [filas]}, accesos_a_mis_datos: [{fecha, accion, rol, entidad}]}`. Audita `ARCO_EXPORTACION_DATOS` |
| `GET /arco/solicitudes` | BIENESTAR, ADMIN | query: `estado`, `tipo`, `vencidas=true`, `page`, `page_size` | `{items, total, page, page_size}` ordenado por plazo |
| `GET /arco/solicitudes/{id}` | BIENESTAR, ADMIN (con alcance), ESTUDIANTE (solo la propia, si no `404 ARCO_NO_ENCONTRADA`) | — | `SolicitudArco` |
| `PATCH /arco/solicitudes/{id}` | BIENESTAR, ADMIN | `{"estado": "EN_TRAMITE"\|"RESUELTA"\|"RECHAZADA", "respuesta": "texto"}` | `SolicitudArco`. Cerrar (`RESUELTA`/`RECHAZADA`) exige `respuesta` (si rechaza, explicar el motivo): `422 RESPUESTA_REQUERIDA`; notifica al estudiante. `409 ARCO_CERRADA`, `422 ESTADO_INVALIDO` |
| `POST /arco/solicitudes/{id}/prorrogar` | BIENESTAR, ADMIN | `{"motivo": "10–500 caracteres"}` | `SolicitudArco` con nueva `fecha_limite`. `409 ARCO_YA_PRORROGADA`, `409 ARCO_CERRADA`, `422 MOTIVO_REQUERIDO` |

Nota: ejecutar una *cancelación* efectiva de datos se hace con `POST /consentimiento/revocar` (la gestión ARCO solo registra y responde).

---

# 3. AQ-10 (RF-09/10/11, HU-06) — tamizaje, no diagnóstico

**El resultado solo lo ven BIENESTAR y el propio ESTUDIANTE.** Docente, Coordinador, Familiar y Admin reciben `403`. Respuestas y puntaje se guardan cifrados; el puntaje se calcula **en el backend** (el cliente nunca recibe la lógica de puntuación). El puntaje y las respuestas **nunca** salen hacia la IA ni a la auditoría.

### `GET /aq10/formulario` — BIENESTAR, ESTUDIANTE (con F0)

```json
{"cuestionario_id": 1, "version": "1.0", "nombre": "…", "idioma": "es-CO", "fuente": "Allison, Auyeung & Baron-Cohen (2012)…",
 "items": [{"numero": 1, "texto": "A menudo noto pequeños sonidos que los demás no notan."}],
 "opciones": [{"valor": 1, "etiqueta": "Totalmente de acuerdo"}, {"valor": 2, "etiqueta": "Ligeramente de acuerdo"},
              {"valor": 3, "etiqueta": "Ligeramente en desacuerdo"}, {"valor": 4, "etiqueta": "Totalmente en desacuerdo"}],
 "instrucciones": "…", "mensaje_tamizaje": "El AQ-10 es una herramienta de tamizaje: no es un diagnóstico…",
 "protocolo_bienvenida": {"titulo": "Antes de empezar", "pasos": ["…"], "ayuda": "…"},
 "revision_linguistica_pendiente": true}
```

Mostrar el `protocolo_bienvenida` antes de la autoaplicación. Lee la configuración de `services/aq10_config` (slice A); si no hay versión activa, usa la semilla `data/aq10.py`.

### `POST /estudiantes/{estudiante_id}/aq10` — BIENESTAR (asistida), ESTUDIANTE propio (autoaplicación) — `201`

La modalidad se deduce del rol (`ASISTIDA` / `AUTOAPLICADA`). Cuerpo: `{"respuestas": {"1": 1, "2": 3, "3": 4, "4": 3, "5": 2, "6": 2, "7": 1, "8": 2, "9": 3, "10": 4}}` — los 10 ítems, valores de las `opciones` (1–4).

Respuesta (puntaje ≥ corte; el corte sale del parámetro `aq10_punto_corte`, por defecto 6):

```json
{"id": 5, "estudiante_id": 7, "cuestionario_id": 1, "modalidad": "ASISTIDA", "aplicado_at": "2026-11-16T15:00:00+00:00",
 "aplicado_por_id": 3, "puntaje": 7, "punto_corte_aplicado": 6, "supera_umbral": true, "flujo_activado": true,
 "respuestas": {"1": 1, "…": 4}, "mensaje_tamizaje": "El AQ-10 es una herramienta de tamizaje: …",
 "ruta_maar_tea_activada": true, "f1_pendiente_creada": true,
 "mensaje": "Gracias por responder. Con este resultado, Bienestar le propondrá conocer mejor cómo aprende …"}
```

* `≥ corte`: marca `flujo_activado`, crea el F1 pendiente (`caracterizacion` `INCOMPLETA`, versión 1) y notifica a Bienestar (evento `AQ10_POSITIVO`, push + correo; el aviso no incluye el puntaje).
* `< corte`: se archiva; devuelve `ruta_maar_tea_activada:false`, `mensaje` («puede volver a solicitarlo») y `recursos_bienestar: [{titulo, descripcion}]`.
* Autoaplicación: una sola vez cada 30 días (`409 AQ10_YA_APLICADO`; Bienestar puede repetir cuando quiera).

Errores: `422 AQ10_INCOMPLETO` (`faltan: [..]`), `422 AQ10_RESPUESTAS_INVALIDAS`, `409 AQ10_YA_APLICADO`, `403 ESTUDIANTE_SIN_CONSENTIMIENTO` / `CONSENTIMIENTO_REQUERIDO`, `403 ACCESO_DENEGADO`.

### `GET /estudiantes/{estudiante_id}/aq10` — BIENESTAR, ESTUDIANTE propio (auditado: `ACCESO_AQ10`)

`{"items": [<mismo objeto de la aplicación, más reciente primero>], "total": n, "mensaje_tamizaje": "…"}`.

---

# 4. F1 Caracterización y F2 Fortalezas (RF-12/13, HU-07/08)

Permisos (matriz §12.1): **lectura** BIENESTAR, COORDINADOR (de su programa), ESTUDIANTE (propio), FAMILIAR (solo con autorización de alcance `CARACTERIZACION`); **escritura** BIENESTAR; el ESTUDIANTE aporta con su voz: en F1 solo `autodescripcion` (y comentarios); en F2 todas las secciones. **DOCENTE y ADMIN: `403`.**

Guardado parcial: cada sección tiene su `PATCH` y es **idempotente** (mismo cuerpo = mismo resultado). En las secciones de lista (`items`) cada elemento se busca por su clave natural (o por `id`) y se **actualiza o crea**; `quitar: [clave | id]` archiva elementos. Campos de texto sensibles se cifran en reposo.

Versionado: mientras el formato esté `INCOMPLETA`/`EN_REVISION` se edita en el sitio. Si está `COMPLETA` y alguien lo modifica, se crea la **versión siguiente** (copia + cambio) y la anterior queda como historial `COMPLETA`. La nueva nace `INCOMPLETA` (si edita Bienestar) o `EN_REVISION` (si edita el estudiante) y se vuelve a confirmar con `POST …/confirmar`.

Respuesta de todo `PATCH` de sección: `{"seccion": "sensorial", "guardado": true, <objeto Progreso>}`.

Objeto **Progreso**:

```json
{"formato": "F1", "version": 1, "estado": "INCOMPLETA", "porcentaje": 50,
 "secciones": [{"clave": "comunicacion", "nombre": "Comunicación", "obligatoria": true, "completa": true}],
 "faltantes": ["Perfil sensorial", "Autonomía", "Preferencias"], "puede_confirmar": false}
```

`porcentaje` = secciones obligatorias completas / obligatorias. Obligatorias F1: `historia_academica`, `comunicacion`, `sensorial`, `autonomia`, `preferencias`, `resumen` (`autodescripcion` es opcional). Obligatorias F2: `fortalezas`, `intereses`, `estrategias`, `metas` (`narrativas` opcional). Sección completa = al menos un elemento / un campo con texto.

## F1 — rutas (`/estudiantes/{estudiante_id}/caracterizacion…`)

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET …/caracterizacion` | BIENESTAR, COORDINADOR, ESTUDIANTE, FAMILIAR | F1 completo de la versión vigente (auditado). Si no existe: `existe:false`, `version:0`, listas vacías (no es error) |
| `GET …/caracterizacion/progreso` | ídem | Objeto Progreso |
| `GET …/caracterizacion/vista-previa` | ídem | Perfil generado (auditado): `{estudiante_id, formato, version, estado, bloques: [{titulo, lineas: [..]}], aviso, progreso}` |
| `PATCH …/caracterizacion/{seccion}` | BIENESTAR; ESTUDIANTE solo `autodescripcion` | Guarda la sección (ver cuerpos). Estudiante en otra sección: `403 SECCION_SOLO_BIENESTAR` |
| `POST …/caracterizacion/confirmar` | BIENESTAR | `200` Progreso con `estado:"COMPLETA"`. `409 FORMATO_INCOMPLETO` (`faltantes`), `409 FORMATO_YA_CONFIRMADO` |
| `POST /estudiantes/{id}/comentarios-formato` | BIENESTAR, ESTUDIANTE | Comentario por sección (no crea versión). Cuerpo `{"formato": "F1"\|"F2", "seccion": "sensorial", "texto": "…"}` → `201 {id, formato, seccion, texto, autor_rol, created_at}`. Los comentarios vienen en `comentarios` de F1/F2 |

Cuerpos de `PATCH …/caracterizacion/{seccion}` (`seccion` ∈ `historia_academica`, `comunicacion`, `sensorial`, `autonomia`, `preferencias`, `resumen`, `autodescripcion`):

```json
// historia_academica (todos opcionales; "" o null borra)
{"trayectoria_escolar": "…", "apoyos_previos": "…", "experiencias_exitosas": "…", "dificultades_previas": "…", "otras_observaciones": "…"}
// comunicacion  (clave: tipo_comunicacion)
{"items": [{"id": null, "tipo_comunicacion": "Verbal", "descripcion": "…", "fortalezas_comunicacion": null, "dificultades_comunicacion": null, "estrategias_favorables": null}], "quitar": ["Verbal"]}
// sensorial  (clave: tipo_sensorial; TipoSensorial)
{"items": [{"tipo_sensorial": "AUDITIVA", "hipersensibilidad": true, "hiposensibilidad": null, "descripcion_experiencia": "…", "impacto_academico": "…", "estrategias_autoregulacion": "…"}]}
// autonomia  (clave: contexto_autonomia; NivelAutonomia)
{"items": [{"contexto_autonomia": "Estudio en casa", "nivel_autonomia": "ALTA", "actividades_autonomas": "…", "actividades_con_apoyo": "…", "actividades_supervisadas": "…"}]}
// preferencias  (clave: tipo_preferencia; prioridad NivelBMAC, por defecto MEDIA)
{"items": [{"tipo_preferencia": "Material anticipado", "descripcion": "…", "prioridad": "ALTA", "razon_preferencia": "…"}]}
// resumen
{"resumen_ejecutivo": "…"}
// autodescripcion (voz del estudiante)
{"autodescripcion_estudiante": "…"}
```

Cada elemento de `items` admite `id` opcional (actualiza ese elemento; `422 ELEMENTO_NO_ENCONTRADO` si no existe). Los campos `descripcion`, `tipo_*`, `contexto_autonomia` son obligatorios en cada elemento. Longitudes: `tipo_comunicacion`, `contexto_autonomia`, `tipo_preferencia` ≤ 100.

Objeto **F1** (`GET …/caracterizacion`):

```json
{"estudiante_id": 7, "formato": "F1", "existe": true, "id": 4, "version": 2, "estado": "EN_REVISION",
 "fecha_caracterizacion": "2026-11-16", "fecha_ultima_actualizacion": "2026-11-16T15:00:00+00:00", "profesional_responsable_id": 3,
 "historia_academica": {"trayectoria_escolar": "…", "apoyos_previos": null, "experiencias_exitosas": null, "dificultades_previas": null, "otras_observaciones": null},
 "comunicacion": [{"id": 1, "tipo_comunicacion": "Verbal", "descripcion": "…", "fortalezas_comunicacion": null, "dificultades_comunicacion": null, "estrategias_favorables": null}],
 "sensorial": [{"id": 1, "tipo_sensorial": "AUDITIVA", "hipersensibilidad": true, "hiposensibilidad": null, "descripcion_experiencia": "…", "impacto_academico": null, "estrategias_autoregulacion": null}],
 "autonomia": [{"id": 1, "contexto_autonomia": "Estudio en casa", "nivel_autonomia": "ALTA", "actividades_autonomas": null, "actividades_con_apoyo": null, "actividades_supervisadas": null}],
 "preferencias": [{"id": 1, "tipo_preferencia": "Material anticipado", "descripcion": "…", "prioridad": "MEDIA", "razon_preferencia": null}],
 "resumen_ejecutivo": "…", "autodescripcion_estudiante": "…",
 "comentarios": [{"id": 1, "seccion": "sensorial", "texto": "…", "autor_rol": "ESTUDIANTE", "created_at": "…"}]}
```

## F2 — rutas (`/estudiantes/{estudiante_id}/fortalezas…`)

Mismas rutas y roles que F1: `GET …/fortalezas`, `GET …/fortalezas/progreso`, `GET …/fortalezas/vista-previa`, `PATCH …/fortalezas/{seccion}`, `POST …/fortalezas/confirmar` (solo BIENESTAR). `seccion` ∈ `fortalezas`, `intereses`, `estrategias`, `metas`, `narrativas`. El estudiante puede escribir en todas las secciones de F2.

```json
// fortalezas (clave: nombre_fortaleza)
{"items": [{"nombre_fortaleza": "Atención al detalle", "descripcion_detallada": "…", "areas_aplicacion": "Registros clínicos", "nivel_consolidacion": "CONSOLIDADA"}]}
// intereses (clave: nombre_interes)
{"items": [{"nombre_interes": "Anatomía", "descripcion": "…", "intensidad": "MODERADO", "aplicacion_academica": "…", "aplicacion_laboral": "…"}]}
// estrategias (clave: nombre_estrategia)
{"items": [{"nombre_estrategia": "Esquemas", "descripcion": "…", "tipo_estrategia": "VISUAL", "efectividad_reportada": "ALTA", "contextos_aplicacion": "…"}]}
// metas (clave: descripcion)
{"items": [{"tipo": "PROFESIONAL", "descripcion": "Trabajar en cuidados intensivos", "plazo": "5 años", "prioridad": "ALTA"}]}
// narrativas (todos opcionales)
{"narrativa_fortalezas": "…", "narrativa_intereses": "…", "narrativa_estrategias": "…"}
```

Objeto **F2** (`GET …/fortalezas`): `{estudiante_id, formato:"F2", existe, id, version, estado, fecha_elaboracion, profesional_responsable_id, fortalezas:[{id,…}], intereses:[…], estrategias:[…], metas:[{id, tipo, descripcion, plazo, prioridad}], narrativas:{narrativa_fortalezas, narrativa_intereses, narrativa_estrategias}, comentarios:[…]}`.

**Regla de servicio `ck_caracterizacion_completa`:** no se pueden crear barreras (F4) mientras el estudiante no tenga una caracterización F1 `COMPLETA` (alguna versión): `409 CARACTERIZACION_INCOMPLETA`.

---

# 5. F3 — Contexto universitario por escenarios (RF-17, HU-09)

Permisos: lectura BIENESTAR, COORDINADOR (su programa), ESTUDIANTE (propio); escritura BIENESTAR (todo); el COORDINADOR **aporta** solo en escenarios y facetas docente/evaluación (no en `resumen`: `403 SECCION_SOLO_BIENESTAR`); el ESTUDIANTE solo lee. DOCENTE/ADMIN/FAMILIAR: `403`.

Un contexto por estudiante y semestre (`semestre` con formato `AAAA-I` o `AAAA-II`, `422 SEMESTRE_INVALIDO`). Bienestar puede crearlo explícitamente (con precarga) o implícitamente con su primer `PATCH`.

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET /mapa/catalogos` | BIENESTAR, COORDINADOR, ESTUDIANTE | Enums y campos de cada escenario, faceta, tipo de barrera y de facilitador (para construir los formularios) |
| `GET /estudiantes/{id}/contextos` | lectura | `{items: [{id, semestre_academico, fecha_analisis, porcentaje}], total}` |
| `POST /estudiantes/{id}/contexto` | BIENESTAR | Cuerpo `{"semestre_academico": "2026-II", "precargar": true}` → `201` Contexto + `precarga`. `409 CONTEXTO_YA_EXISTE`, `422 ESTUDIANTE_SIN_PROGRAMA` |
| `GET /estudiantes/{id}/contexto/{semestre}` | lectura | Contexto. `404 CONTEXTO_NO_ENCONTRADO` |
| `GET /estudiantes/{id}/contexto/{semestre}/progreso` | lectura | Progreso (existe aunque no haya contexto: `existe:false`) |
| `PATCH /estudiantes/{id}/contexto/{semestre}/resumen` | BIENESTAR | `{"resumen_contextual", "factores_protectores", "factores_de_riesgo"}` (textos, todos opcionales) → Progreso |
| `PATCH /estudiantes/{id}/contexto/{semestre}/escenarios/{ESCENARIO}` | BIENESTAR, COORDINADOR | Guarda un escenario (`ESCENARIO` ∈ enum `Escenario`, en mayúsculas). Marcar `aplica:false` si no aplica este semestre → Progreso |
| `PATCH /estudiantes/{id}/contexto/{semestre}/docentes` | BIENESTAR, COORDINADOR | Faceta transversal: `{"items": [{"id": null, "nombre_docente": "…", …}], "quitar": [id]}` → lista de docentes del contexto |
| `PATCH /estudiantes/{id}/contexto/{semestre}/evaluacion` | BIENESTAR, COORDINADOR | Faceta transversal (un registro por contexto) → objeto evaluación |

**Precarga** (`precarga` en la respuesta de `POST`): si existe el contexto del semestre anterior se copian los escenarios y `factores_protectores`; desde F10, si hay un hito `INICIO_PRACTICAS` se sugieren `PRACTICA_CLINICA` y `PRACTICA_SALUD_PUBLICA` (`aplica:true`), y se informa si hay nota de continuidad aprobada para el semestre. `{"origen_semestre": "2026-I"|null, "escenarios_copiados": ["AULA"], "hitos_sugeridos": ["PRACTICA_CLINICA"], "nota_continuidad_aprobada": false}`.

Objeto **Contexto**:

```json
{"id": 2, "estudiante_id": 7, "semestre_academico": "2026-II", "fecha_analisis": "2026-11-16", "responsable_analisis_id": 3,
 "resumen_contextual": null, "factores_protectores": null, "factores_de_riesgo": null,
 "escenarios": {"AULA": {"aplica": true, "descripcion_condiciones": "…", "metodologias_docentes": null, "dinamicas_evaluacion": null,
                         "observaciones": null, "numero_estudiantes": 35, "tipo_aula": "PRESENCIAL", "…": null},
                "CAMPUS": null, "VIRTUALIDAD": null, "LABORATORIOS": null, "PRACTICA_CLINICA": null,
                "PRACTICA_SALUD_PUBLICA": null, "EVENTOS": null, "PASANTIAS": null},
 "docentes": [{"id": 1, "docente_id": null, "nombre_docente": "Prof. X", "…": null}], "evaluacion": null,
 "progreso": {"semestre_academico": "2026-II", "existe": true, "escenarios": [{"escenario": "AULA", "nombre": "Aula teórica", "decidido": true, "aplica": true, "completo": true}],
              "escenarios_decididos": 1, "escenarios_completos": 1, "resumen_completo": false, "porcentaje": 12, "completo": false, "faltantes": ["Campus físico"]},
 "precarga": {"…": "solo en la respuesta de POST"}}
```

Escenario `completo` = decidido y (no aplica, o `descripcion_condiciones` con texto). `completo` global = los 8 escenarios completos + `resumen_contextual` con texto. `porcentaje` = escenarios completos / 8.

### Campos por escenario y faceta (cuerpos de los PATCH de F3)

Todos los campos son opcionales en el PATCH (parcial); `aplica` por defecto `true`.

#### Campos comunes de todo escenario

(ver tabla de cada escenario: `aplica`, `descripcion_condiciones`, `metodologias_docentes`, `dinamicas_evaluacion`, `observaciones` + los propios)

**Escenario AULA (Aula teórica)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `numero_estudiantes` | entero | no |  |
| `tipo_aula` | enum | no | PRESENCIAL, VIRTUAL, HIBRIDA |
| `caracteristicas_ambientales` | texto | no |  |
| `disponibilidad_tecnologia` | texto | no |  |
| `dinamica_interaccion` | texto | no |  |
| `nivel_estructuracion` | enum | no | ALTAMENTE_ESTRUCTURADA, MEDIANAMENTE_ESTRUCTURADA, POCO_ESTRUCTURADA |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario CAMPUS (Campus físico)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `accesibilidad_fisica` | enum | no | BAJA, MEDIA, ALTA |
| `disponibilidad_espacios_tranquilos` | booleano | no |  |
| `ruido_ambiental_nivel` | enum | no | BAJO, MEDIO, ALTO |
| `iluminacion_caracteristica` | texto | no | texto (máx. 255) |
| `servicios_disponibles` | texto | no |  |
| `servicios_bienestar` | texto | no |  |
| `seguridad_percibida` | enum | no | BAJA, MEDIA, ALTA |
| `facilidades_transporte` | texto | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario VIRTUALIDAD (Virtualidad)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `plataformas` | texto | no | texto (máx. 500) |
| `modalidad_clase` | enum | no | SINCRONICA, ASINCRONICA, MIXTA |
| `accesibilidad_plataforma` | enum | no | BAJA, MEDIA, ALTA |
| `camara_obligatoria` | booleano | no |  |
| `clases_grabadas` | booleano | no |  |
| `conectividad_estudiante` | enum | no | BAJA, MEDIA, ALTA |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario LABORATORIOS (Laboratorios)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_laboratorio` | enum | no | QUIMICA, BIOLOGIA, ANATOMIA, SIMULACION_CLINICA, OTRO |
| `aforo` | entero | no |  |
| `ruido_nivel` | enum | no | BAJO, MEDIO, ALTO |
| `olores_o_sustancias_fuertes` | booleano | no |  |
| `trabajo_en_equipo` | booleano | no |  |
| `protocolos_seguridad` | texto | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario PRACTICA_CLINICA (Prácticas clínicas)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `institucion_practica` | texto | no | texto (máx. 255) |
| `servicio_o_area` | texto | no | texto (máx. 200) |
| `turnos` | texto | no | texto (máx. 200) |
| `duracion_turno_horas` | entero | no |  |
| `rotaciones_frecuentes` | booleano | no |  |
| `nivel_estimulos_sensoriales` | enum | no | BAJO, MEDIO, ALTO |
| `tutor_clinico_disponible` | booleano | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario PRACTICA_SALUD_PUBLICA (Prácticas de salud pública)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `entorno_o_comunidad` | texto | no | texto (máx. 255) |
| `trabajo_de_campo` | booleano | no |  |
| `requiere_transporte` | booleano | no |  |
| `interaccion_comunitaria` | enum | no | BAJO, MEDIO, ALTO |
| `imprevisibilidad` | enum | no | BAJO, MEDIO, ALTO |
| `acompanamiento_docente` | booleano | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario EVENTOS (Eventos universitarios)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_evento` | enum | no | ACADEMICO, CULTURAL, DEPORTIVO, OTRO |
| `aforo_estimado` | entero | no |  |
| `ruido_nivel` | enum | no | BAJO, MEDIO, ALTO |
| `programa_previsible` | booleano | no |  |
| `posibilidad_salida_tranquila` | booleano | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Escenario PASANTIAS (Pasantías)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `organizacion` | texto | no | texto (máx. 255) |
| `sector` | texto | no | texto (máx. 200) |
| `modalidad` | enum | no | PRESENCIAL, REMOTA, HIBRIDA |
| `supervisor_asignado` | booleano | no |  |
| `flexibilidad_horaria` | booleano | no |  |
| `ajustes_conversados_con_organizacion` | booleano | no |  |
| `aplica` | booleano | no |  |
| `descripcion_condiciones` | texto | no |  |
| `metodologias_docentes` | texto | no |  |
| `dinamicas_evaluacion` | texto | no |  |
| `observaciones` | texto | no |  |

**Faceta docentes (cada elemento de `items`)**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `docente_id` | entero | no |  |
| `nombre_docente` | texto | no | texto (máx. 255) |
| `estilo_pedagogico` | texto | no | texto (máx. 255) |
| `disponibilidad_apoyo` | enum | no | BAJA, MEDIA, ALTA |
| `capacitacion_inclusion` | booleano | no |  |
| `comunicacion_clara` | booleano | no |  |
| `flexibilidad_metodologica` | booleano | no |  |
| `disposicion_ajustes` | enum | no | RESISTENCIA, NEUTRA, RECEPTIVA |
| `id` | entero | no |  |

**Faceta evaluación**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipos_evaluacion_usados` | texto | no | texto (máx. 500) |
| `claridad_criterios` | enum | no | CLARA, MEDIANAMENTE_CLARA, POCO_CLARA |
| `claridad_instrucciones` | enum | no | CLARA, MEDIANAMENTE_CLARA, POCO_CLARA |
| `tiempo_evaluacion` | enum | no | LIMITADO, MEDIO, FLEXIBLE |
| `ambiente_evaluacion` | texto | no | texto (máx. 500) |
| `retroalimentacion_ofrecida` | booleano | no |  |
| `flexibilidad_formato` | booleano | no |  |


---

# 6. F4 — Mapa de barreras (RF-18/19, HU-10)

Permisos: lectura BIENESTAR, COORDINADOR, ESTUDIANTE; crear/modificar/archivar BIENESTAR; el ESTUDIANTE **aporta** barreras propias (puede modificar/archivar solo las que registró: `403 SOLO_PROPIOS`). `POST /barreras/{id}/persistente` solo BIENESTAR. DOCENTE/ADMIN/FAMILIAR: `403`.

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET /estudiantes/{id}/barreras` | lectura | Query `tipo_barrera`, `escenario`, `estado`, `semestre_academico` → `{items: [Barrera], total}` |
| `POST /estudiantes/{id}/barreras` | BIENESTAR, ESTUDIANTE | `201 Barrera`. `409 CARACTERIZACION_INCOMPLETA` (F1 sin confirmar) |
| `GET /barreras/{id}` | lectura | `Barrera` |
| `PATCH /barreras/{id}` | BIENESTAR, ESTUDIANTE (propias) | Parcial; `detalle` se fusiona sobre el existente. No cambia el `tipo_barrera` |
| `DELETE /barreras/{id}?motivo=…` | BIENESTAR, ESTUDIANTE (propias) | Archiva (soft delete) |
| `POST /barreras/{id}/persistente` | BIENESTAR | Marca `PERSISTENTE` (persiste tras DUA, paso 7). Cuerpo `{"observacion": "opcional"}` |

Cuerpo de `POST`:

```json
{"tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "descripcion_barrera": "Las instrucciones se dan solo de forma oral.",
 "contexto_aparicion": null, "frecuencia": "FRECUENTE", "severidad": "MODERADA",
 "impacto_participacion": false, "impacto_aprendizaje": true, "impacto_bienestar": false, "impacto_permanencia": false,
 "origen_percibido": null, "fecha_identificacion": null, "semestre_academico": null,
 "detalle": {"tipo_comunicacion_problema": "Instrucciones orales"}}
```

* `tipo_barrera` (alias aceptado: `tipo`) ∈ `TipoBarrera`; `escenario` ∈ `Escenario` o `null`; `descripcion_barrera` obligatoria (≥3); `frecuencia` por defecto `FRECUENTE`; `severidad` por defecto `MODERADA`; `fecha_identificacion` por defecto hoy; `semestre_academico` por defecto el semestre actual (`AAAA-I`/`AAAA-II`).
* `detalle` depende del tipo (tablas abajo); campos desconocidos → `422 DETALLE_INVALIDO`.
* **RF-19:** una barrera `SOCIAL` exige `detalle.propuesta_respuesta_institucional` no vacía → `422 BARRERA_SOCIAL_SIN_RESPUESTA_INSTITUCIONAL` (también al modificar).

Objeto **Barrera**: `{id, estudiante_id, tipo_barrera, escenario, descripcion_barrera, contexto_aparicion, frecuencia, severidad, impacto_participacion, impacto_aprendizaje, impacto_bienestar, impacto_permanencia, origen_percibido, fecha_identificacion, estado, semestre_academico, registrada_por_id, detalle: {…}, facilitadores_que_la_mitigan: [facilitador_id], aviso: "La barrera es del entorno, no de la persona."}`.

### `detalle` según el tipo de barrera

**Detalle de barrera ACTITUDINAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `actores_implicados` | texto | no | texto (máx. 500) |
| `tipo_actitud` | enum | no | PREJUICIO, ESTIGMA, FALTA_CONOCIMIENTO, SOBREPROTECCION, EXCLUSION |
| `evidencia` | texto | no |  |

**Detalle de barrera COMUNICATIVA**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_comunicacion_problema` | texto | no | texto (máx. 255) |
| `descripcion_problema` | texto | no |  |
| `consecuencias` | texto | no |  |

**Detalle de barrera PEDAGOGICA**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `metodologia_problematica` | texto | no | texto (máx. 255) |
| `razon_problema` | texto | no |  |
| `alternativas_exitosas` | texto | no |  |

**Detalle de barrera EVALUATIVA**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `aspecto_evaluativo` | enum | no | INSTRUCCIONES, TIEMPO, AMBIENTE, FORMATO, CRITERIOS |
| `descripcion_problema` | texto | no |  |
| `impacto_calificaciones` | texto | no |  |

**Detalle de barrera SENSORIAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_sensorial` | enum | sí | AUDITIVA, VISUAL, TACTIL, OLFATIVA, GUSTATIVA, VESTIBULAR, PROPIOCEPCION |
| `hipersensibilidad` | booleano | no |  |
| `hiposensibilidad` | booleano | no |  |
| `estimulos_problematicos` | texto | no |  |
| `impacto_en_clase` | texto | no |  |

**Detalle de barrera SOCIAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_interaccion` | texto | no | texto (máx. 255) |
| `descripcion_dificultad` | texto | no |  |
| `consecuencias_sociales` | texto | no |  |
| `propuesta_respuesta_institucional` | texto | no |  |

**Detalle de barrera INSTITUCIONAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `politica_procedimiento` | texto | no | texto (máx. 500) |
| `impacto_acceso` | booleano | no |  |
| `impacto_permanencia` | booleano | no |  |
| `sugerencia_cambio` | texto | no |  |

**Detalle de barrera TECNOLOGICA**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_tecnologia` | texto | no | texto (máx. 255) |
| `problema_especifico` | texto | no |  |
| `disponibilidad_alternativas` | booleano | no |  |


---

# 7. F5 — Mapa de facilitadores (RF-20, HU-11)

Permisos como F4 (recurso `FACILITADORES`).

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET /estudiantes/{id}/facilitadores` | lectura | Query `tipo_facilitador` → `{items: [Facilitador], total}` |
| `POST /estudiantes/{id}/facilitadores` | BIENESTAR, ESTUDIANTE | `201 Facilitador` (no exige F1 confirmada) |
| `GET /facilitadores/{id}` | lectura | `Facilitador` |
| `PATCH /facilitadores/{id}` | BIENESTAR, ESTUDIANTE (propios) | Parcial; si se envía `barreras_mitigadas` **reemplaza** los vínculos |
| `PUT /facilitadores/{id}/barreras` | BIENESTAR, ESTUDIANTE (propios) | `{"barrera_ids": [1, 2]}` reemplaza los vínculos. `422 BARRERAS_INVALIDAS` si alguna no es del mismo estudiante |
| `DELETE /facilitadores/{id}?motivo=…` | BIENESTAR, ESTUDIANTE (propios) | Archiva |
| `GET /estudiantes/{id}/resumen-barrera-facilitador` | lectura | Vista cruzada |

Cuerpo de `POST`:

```json
{"tipo_facilitador": "TECNOLOGICO", "nombre_facilitador": "Lector de pantalla", "descripcion_detallada": "Lee los textos en voz alta.",
 "contextos_donde_opera": "Aula y casa", "intensidad_impacto": "MODERADA", "renovabilidad": "FIJO",
 "fecha_identificacion": null, "potencial_de_uso": "Podría ofrecerse a todo el grupo.",
 "detalle": {"tipo_tecnologia": "Lector", "funcionalidad_apoyo": "…", "disponibilidad": "GRATUITA"},
 "barreras_mitigadas": [1]}
```

`tipo_facilitador` (alias `tipo`) ∈ `TipoFacilitador`. Objeto **Facilitador**: `{id, estudiante_id, tipo_facilitador, nombre_facilitador, descripcion_detallada, contextos_donde_opera, intensidad_impacto, renovabilidad, fecha_identificacion, potencial_de_uso, registrado_por_id, detalle: {…}, barreras_mitigadas: [barrera_id]}`.

**Vista cruzada** `GET /estudiantes/{id}/resumen-barrera-facilitador`:

```json
{"estudiante_id": 7,
 "barreras": [{"id": 1, "tipo_barrera": "COMUNICATIVA", "escenario": "AULA", "severidad": "MODERADA", "estado": "IDENTIFICADA",
               "descripcion_barrera": "…", "facilitadores": [{"id": 2, "tipo_facilitador": "TECNOLOGICO", "nombre_facilitador": "Lector de pantalla"}]}],
 "facilitadores_sin_barrera": [{"id": 3, "tipo_facilitador": "PERSONAL", "nombre_facilitador": "Constancia"}],
 "barreras_sin_facilitador": [4],
 "totales": {"barreras": 3, "facilitadores": 2, "barreras_sin_facilitador": 1, "barreras_persistentes": 0}}
```

### `detalle` según el tipo de facilitador

**Detalle de facilitador PERSONAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `caracteristica_personal` | texto | no | texto (máx. 255) |
| `evidencia_fortaleza` | texto | no |  |

**Detalle de facilitador PEDAGOGICO**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_estrategia` | texto | no | texto (máx. 255) |
| `docentes_que_usan` | texto | no | texto (máx. 500) |

**Detalle de facilitador SOCIAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_relacion` | enum | no | AMISTAD, FAMILIA, MENTOR, GRUPO_PARES, COMUNIDAD |
| `actores_implicados` | texto | no | texto (máx. 500) |

**Detalle de facilitador INSTITUCIONAL**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `politica_recurso` | texto | no | texto (máx. 255) |
| `accesibilidad_actual` | texto | no | texto (máx. 500) |

**Detalle de facilitador TECNOLOGICO**

| Campo | Tipo | Req. | Valores permitidos |
|---|---|---|---|
| `tipo_tecnologia` | texto | no | texto (máx. 255) |
| `funcionalidad_apoyo` | texto | no |  |
| `disponibilidad` | enum | no | INSTITUCIONAL, PERSONAL, GRATUITA, PAGO |


---

# 8. Motor DUA M3 — sugerencias (RF-15/16, HU-12)

Sugiere, **nunca impone**. Permisos (recurso `BARRERAS`): generar y decidir solo BIENESTAR; lectura BIENESTAR y COORDINADOR; el ESTUDIANTE ve únicamente las `ACEPTADA`/`MODIFICADA` (las demás: `403`). DOCENTE/ADMIN/FAMILIAR: `403` (el docente recibe las estrategias acordadas a través del Plan, slice C1).

Algoritmo: perfil abstracto (tipos de barrera, escenarios, severidad, principios y rasgos funcionales como etiquetas de enum, p. ej. `SENS_AUDITIVA`; nunca nombre, puntaje AQ-10 ni diagnóstico) → similitud coseno (scikit-learn) contra `CASO_CBR` ponderada por la efectividad registrada (semáforo). Con menos de 3 casos relevantes recomienda por reglas (tipo de barrera + escenario) sobre el catálogo (`origen: "FILTRO_CATALOGO"`); con casos suficientes combina reglas (40 %) y evidencia (60 %) (`origen: "CBR"`). Lo rechazado no reaparece para esa barrera y entra como caso negativo anónimo.

| Método y ruta | Roles | Descripción |
|---|---|---|
| `POST /estudiantes/{id}/sugerencias/generar` | BIENESTAR | Cuerpo `{"barrera_ids": null, "max_por_barrera": 3}` (1–10). `201 {creadas: [Sugerencia], actualizadas: [Sugerencia], barreras_evaluadas: [id], barreras_sin_cobertura: [id], detail}`. Idempotente (no duplica). `409 SIN_BARRERAS`, `422 BARRERAS_INVALIDAS` |
| `GET /estudiantes/{id}/sugerencias` | BIENESTAR, COORDINADOR, ESTUDIANTE | Filtros: `estado`, `principio`, `pauta` (1–9), `escenario`, `tipo_barrera`, `barrera_id`. `{items, total}` por puntaje desc. |
| `GET /sugerencias/{id}` | ídem | `Sugerencia` |
| `POST /sugerencias/{id}/aceptar` | BIENESTAR | Cuerpo opcional `{"nota": "…"}` → `Sugerencia` `ACEPTADA`. `409 SUGERENCIA_YA_DECIDIDA` |
| `POST /sugerencias/{id}/modificar` | BIENESTAR | `{"texto_modificado": "≥5 caracteres", "motivo": "opcional"}` → `MODIFICADA` (también desde `ACEPTADA`/`MODIFICADA`). Guarda la versión editada |
| `POST /sugerencias/{id}/rechazar` | BIENESTAR | `{"motivo": "≥5 caracteres"}` obligatorio → `RECHAZADA` (`422 MOTIVO_REQUERIDO`); retroalimenta el CBR |
| `POST /sugerencias/{id}/texto-accesible` | BIENESTAR | Genera y guarda el «texto accesible» para docentes: `{sugerencia_id, texto_accesible, origen: "OPENAI"\|"PLANTILLA", modelo}`. `409 SUGERENCIA_RECHAZADA`, `422 SUGERENCIA_SIN_ESCENARIO` |
| `GET /sugerencias/catalogo` | BIENESTAR, COORDINADOR, DOCENTE | Catálogo DUA activo (solo lectura). Filtros `principio`, `pauta`, `escenario`, `tipo_barrera` → `{items: [{id, codigo, nombre, descripcion_pedagogica, principio, pauta, pauta_nombre, punto_verificacion, escenarios, tipos_barrera}], total}` |

Objeto **Sugerencia**:

```json
{"id": 12, "estudiante_id": 7, "barrera_id": 1, "plan_id": null, "tipo_barrera": "COMUNICATIVA", "escenario": "AULA",
 "principio_dua": "REPRESENTACION", "origen": "FILTRO_CATALOGO", "puntaje": 0.8333,
 "justificacion": "Esta estrategia es pertinente porque el estudiante tiene barrera de tipo COMUNICATIVA en el escenario AULA. Corresponde al principio DUA «Múltiples formas de representación» (pauta 2: Lenguaje y símbolos). El catálogo institucional la recomienda para ese escenario. Es una sugerencia: usted decide si la acepta, la modifica o la rechaza.",
 "estado": "PROPUESTA", "motivo_decision": null, "texto_modificado": null, "texto_accesible": null,
 "decidido_por_id": null, "decidido_at": null, "created_at": "…",
 "estrategia": {"id": 3, "codigo": "DUA-R-2.1-01", "nombre": "…", "descripcion_pedagogica": "…", "principio": "REPRESENTACION",
                "pauta": 2, "pauta_nombre": "Lenguaje y símbolos", "punto_verificacion": "2.1", "escenarios": ["AULA"], "tipos_barrera": ["COMUNICATIVA"]}}
```

**Privacidad IA (RF-11/16, D4):** `services/ai_gateway.py` es el único módulo que habla con OpenAI y solo recibe `AIPromptInput(tipo_barrera, escenario, principio_dua)` validado contra enums; el mensaje enviado es un JSON con exactamente esos tres campos. Sin `OPENAI_API_KEY`, sin `langchain_openai` o ante un error, devuelve una plantilla determinista en español (`origen: "PLANTILLA"`).

**Para el slice C1:** `app.services.sugerencias.get_accepted(db, estudiante_id, *, plan_id=None) -> list[SugerenciaDua]` devuelve las sugerencias `ACEPTADA`/`MODIFICADA`; texto vigente = `texto_modificado` si existe, o `EstrategiaDuaCatalogo.descripcion_pedagogica` (`estrategia_catalogo_id`).

---

# 9. Códigos de error del slice

`CONSENTIMIENTO_REQUERIDO`, `ESTUDIANTE_SIN_CONSENTIMIENTO`, `CONSENTIMIENTO_YA_FIRMADO`, `CONSENTIMIENTO_REVOCADO`, `SIN_CONSENTIMIENTO_VIGENTE`, `TEXTO_DESACTUALIZADO`, `ACEPTACION_REQUERIDA`, `NOMBRE_NO_COINCIDE`, `ESTUDIANTE_REQUERIDO`, `CONFIRMACION_REQUERIDA`, `ARCO_NO_ENCONTRADA`, `ARCO_CERRADA`, `ARCO_YA_PRORROGADA`, `DESCRIPCION_MUY_CORTA`, `RESPUESTA_REQUERIDA`, `MOTIVO_REQUERIDO`, `ESTADO_INVALIDO`, `AQ10_INCOMPLETO`, `AQ10_RESPUESTAS_INVALIDAS`, `AQ10_YA_APLICADO`, `SECCION_SOLO_BIENESTAR`, `FORMATO_INCOMPLETO`, `FORMATO_YA_CONFIRMADO`, `ELEMENTO_NO_ENCONTRADO`, `SIN_PROFESIONAL`, `SEMESTRE_INVALIDO`, `CONTEXTO_NO_ENCONTRADO`, `CONTEXTO_YA_EXISTE`, `ESTUDIANTE_SIN_PROGRAMA`, `CARACTERIZACION_INCOMPLETA`, `BARRERA_NO_ENCONTRADA`, `BARRERA_SOCIAL_SIN_RESPUESTA_INSTITUCIONAL`, `DETALLE_INVALIDO`, `SOLO_PROPIOS`, `FACILITADOR_NO_ENCONTRADO`, `BARRERAS_INVALIDAS`, `SIN_BARRERAS`, `SUGERENCIA_NO_ENCONTRADA`, `SUGERENCIA_YA_DECIDIDA`, `SUGERENCIA_RECHAZADA`, `SUGERENCIA_SIN_ESCENARIO`, además de los generales `ACCESO_DENEGADO`, `ROL_NO_PERMITIDO`, `ESTUDIANTE_NO_ENCONTRADO`, `DATOS_INVALIDOS`.

## Tablas nuevas (migración `00B1`)

`consentimiento_detalle`, `solicitud_arco`, `barrera_facilitador`, `historia_academica`, `meta_estudiante`, `formato_comentario`, `perfil_fortalezas_estado` (solo tablas nuevas; ver `app/models/slice_b.py`).
