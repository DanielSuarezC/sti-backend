# API slice C3: Trayectoria (M8), F10, panel del Docente y Familiar Autorizado

Prefijo `/api/v1`. Auth: `Authorization: Bearer <jwt>` (ver `auth.md`). Errores: `{"detail": "...", "code": "SNAKE_CASE"}`
(los 422 de validación agregan `errores: [{campo, mensaje}]`). Fechas ISO-8601 (`2026-11-16`); semestres `AAAA-I` / `AAAA-II`.
Todo lo del estudiante exige F0 firmado (`403 CONSENTIMIENTO_REQUERIDO` para el propio estudiante; `403 ESTUDIANTE_SIN_CONSENTIMIENTO`
para el resto de roles). Sin token: `401 NO_AUTENTICADO`. Rol no permitido: `403 ROL_NO_PERMITIDO`. Fuera de alcance: `403 ACCESO_DENEGADO`.

En las rutas `/estudiantes/{estudiante_id}/...` de trayectoria/F10, `{estudiante_id}` puede ser el id numérico o la palabra `mi`
(el estudiante autenticado). Las rutas de familiares del estudiante usan siempre `/estudiantes/mi/familiares`.

## Matriz de acceso (arquitectura §12.1)

| Recurso | Bienestar | Coordinador (su programa) | Docente | Estudiante | Familiar | Admin |
|---|---|---|---|---|---|---|
| Trayectoria, hitos, F10 (componentes 1 y 2) | CRUD | Lectura | No | Lectura propia (+ aprueba el F10) | No | No |
| Notas de continuidad | CRUD de lo que elabora | Lectura **solo APROBADA** | **No** | Lee todo lo suyo, redacta, aprueba/rechaza | No | No |
| Panel docente | No | No | Solo sus asignaturas | No | No | No |
| Autorizaciones de familiar | No | No | No | Otorga/edita/revoca las propias | No | No |
| Lectura de familiar | No | No | No | No | Solo lo autorizado, solo lectura | No |

---

## 1. Trayectoria académica (D9)

Objeto **Trayectoria** (un semestre):

```json
{ "id": 1, "estudiante_id": 5, "semestre_academico": "2026-II", "fecha_inicio_semestre": "2026-08-03",
  "fecha_fin_semestre": null, "asignaturas_inscritas": 2, "asignaturas_completadas": null, "creditos_aprobados": 8,
  "promedio_academico": 4.2,
  "dimensiones": { "ACCESO": null, "PARTICIPACION": { "asistencia_promedio": 95.0, "participacion_clase": "ALTA", "...": "..." },
                   "APRENDIZAJE": null, "BIENESTAR": null, "AUTONOMIA": null, "PERMANENCIA": { "...": "..." },
                   "PROGRESION": null, "GRADUACION": null, "TRANSICION_PROFESIONAL": null } }
```

`dimensiones` siempre trae las 9 claves; `null` = sección sin diligenciar. Campos de cada dimensión (todos opcionales en PATCH; claves
desconocidas → 422):

| Dimensión | Campos |
|---|---|
| `ACCESO` | `puede_ingresar_aulas`, `puede_usar_biblioteca`, `puede_usar_laboratorios`, `puede_acceder_plataforma`, `puede_usar_servicios_bienestar` (bool); `barreras_acceso_identificadas`, `ajustes_acceso_implementados` (texto) |
| `PARTICIPACION` | `asistencia_promedio` (0-100), `participacion_clase` (`BAJA|MEDIA|ALTA|VARIABLE`), `actividades_extracurriculares` (int), `trabajo_colaborativo` (`AISLADO|CON_APOYO|INDEPENDIENTE`), `interaccion_pares` (texto), `liderazgo_grupos` (bool) |
| `APRENDIZAJE` | `demuestra_competencias`, `necesidad_tutoria` (bool), `calificaciones_promedio` (0-5), `asignaturas_aprobadas_porcentaje` (0-100), `mejora_academica`, `aprendizajes_significativos` (texto) |
| `BIENESTAR` | `percepcion_bienestar`, `ansiedad_nivel`, `seguridad_percibida` (`BAJA|MEDIA|ALTA`), `depresion_indicadores`, `siente_pertenencia` (bool), `apoyo_socioafectivo` (texto), `balance_vida_estudio` (`DESEQUILIBRADO|MEDIANO|EQUILIBRADO`) |
| `AUTONOMIA` | `gestiona_su_agenda`, `solicita_apoyos_autonomamente` (bool), `autorregulacion`, `capacidad_resolucion_problemas` (`BAJA|MEDIA|ALTA`), `independencia_tareas_academicas` (`TOTAL_DEPENDENCIA|PARCIAL_DEPENDENCIA|INDEPENDENCIA_PARCIAL|TOTAL_INDEPENDENCIA`), `incremento_autonomia` |
| `PERMANENCIA` | `continua_matriculado` (bool), `riesgo_desersion` (`BAJO|MEDIO|ALTO`), `factores_riesgo`, `factores_proteccion`, `plan_retencion`, `cambios_circunstancias` |
| `PROGRESION` | `semestres_completados`, `avance_plan_estudios_porcentaje`, `creditosfaltantes` (nombre del ERD), `asignaturas_pendientes` (int), `tiempo_estimado_graduacion` (texto), `probabilidad_graduacion` (`BAJA|MEDIA|ALTA`) |
| `GRADUACION` | `ha_graduado` (bool), `fecha_graduacion`, `grado_obtenido`, `estado_trabajofinal_tesis` (`NO_APLICA|NO_INICIADO|CURSANDO|APROBADO|GRADUADO`), `satisfaccion_formacion` (`INSATISFECHO|NEUTRAL|SATISFECHO|MUY_SATISFECHO`), `logros_academicos` |
| `TRANSICION_PROFESIONAL` | `experiencia_practica_laboral` (bool), `horas_practica_laboral`, `sector_interes_profesional`, `capacidades_laborales`, `necesidades_apoyo_laboral`, `ajustes_laborales_identificados`, `estado_laboral_actual` (`DESEMPLEADO|EMPLEADO_TEMPORAL|EMPLEADO_FIJO|EMPRENDEDOR|INACTIVO`), `satisfaccion_laboral` |

Cada dimensión devuelta incluye exactamente esos campos con su valor actual (o el valor por defecto del modelo).

| Método y ruta | Roles | Cuerpo | Respuesta | Errores (`code`) |
|---|---|---|---|---|
| `POST /estudiantes/{id}/trayectoria` | BIENESTAR | `{semestre_academico, fecha_inicio_semestre?, fecha_fin_semestre?, asignaturas_inscritas?, asignaturas_completadas?, creditos_aprobados?, promedio_academico? (0-5), dimensiones?: {ACCESO?: {...}, ...}}` | `201 Trayectoria` | `409 TRAYECTORIA_DUPLICADA`, `422 FECHA_INICIO_REQUERIDA` (si no hay calendario del semestre), `422 FECHAS_INVALIDAS`, `422 ASIGNATURAS_INCOHERENTES`, `422 DATOS_INVALIDOS` |
| `GET /estudiantes/{id}/trayectoria` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `{estudiante_id, resumen: Resumen, trayectorias: [Trayectoria] (orden cronológico), hitos: [Hito]}` | `403 ACCESO_DENEGADO` |
| `GET /estudiantes/{id}/trayectoria/resumen` | ídem | — | `Resumen` | ídem |
| `GET /estudiantes/{id}/trayectoria/{semestre}` | ídem | — | `Trayectoria` | `404 TRAYECTORIA_NO_ENCONTRADA` |
| `PATCH /estudiantes/{id}/trayectoria/{semestre}` | BIENESTAR | parcial: campos del semestre + `dimensiones` (solo las secciones enviadas, parcial dentro de cada una) | `Trayectoria` | `404 TRAYECTORIA_NO_ENCONTRADA`, `422` |
| `PATCH /estudiantes/{id}/trayectoria/{semestre}/dimensiones/{DIMENSION}` | BIENESTAR | los campos de esa dimensión (parcial). `{DIMENSION}` = una de las 9 claves | `Trayectoria` | `422 DATOS_INVALIDOS` |
| `GET /estudiantes/{id}/hitos` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `[Hito]` | |
| `POST /estudiantes/{id}/hitos` | BIENESTAR | `{tipo_hito, fecha_hito, descripcion?, semestre_academico?}` | `201 Hito` | `404 TRAYECTORIA_NO_ENCONTRADA` |
| `PATCH /estudiantes/{id}/hitos/{hito_id}` | BIENESTAR | `{tipo_hito?, fecha_hito?, descripcion?}` | `Hito` | `404 HITO_NO_ENCONTRADO` |
| `DELETE /estudiantes/{id}/hitos/{hito_id}` | BIENESTAR | — | `{detail}` (soft delete) | `404 HITO_NO_ENCONTRADO` |

`tipo_hito`: `CAMBIO_SEMESTRE | MATERIA_CLAVE | INICIO_PRACTICAS | TRABAJO_GRADO | GRADUACION | OTRO`.

```json
// Hito
{ "id": 3, "estudiante_id": 5, "trayectoria_id": 2, "semestre_academico": "2026-II", "tipo_hito": "MATERIA_CLAVE",
  "fecha_hito": "2026-11-20", "descripcion": "Aprobó Anatomía", "registrado_por_id": 2 }

// Resumen
{ "semestres_cursados": 2, "creditos_aprobados": 25,
  "estado_permanencia": { "semestre_academico": "2026-II", "continua_matriculado": true, "riesgo_desersion": "BAJO" },
  "proyeccion_graduacion": { "semestres_registrados": 2, "nivel_semestre_actual": 2, "creditos_aprobados_total": 25,
      "duracion_semestres_programa": 8, "creditos_programa": 160, "semestres_restantes": 6,
      "semestre_estimado_graduacion": "2029-II", "avance_creditos_porcentaje": 16 },
  "necesidades_siguiente_semestre": { "nivel_semestre": 3, "fuente": "ASIGNATURAS|PARAMETRO|PROGRAMA|SIN_DATOS",
      "asignaturas": [ { "asignatura_id": 9, "codigo": "ENF301", "nombre": "Práctica clínica I", "creditos": 6,
                         "es_practica": true, "escenario_predominante": "PRACTICA_CLINICA" } ],
      "creditos_previstos": 6, "notas_plan_estudios": null,
      "necesidades": [ { "tipo": "PRACTICAS", "semestre_nivel": 3, "escenarios_sugeridos": ["PRACTICA_CLINICA", "PRACTICA_SALUD_PUBLICA"],
                         "descripcion": "El semestre incluye prácticas: ..." } ] },
  "ultimo_semestre": "2026-II" }
```

**Proyección de necesidades (plan de estudios).** Se calcula con (1) las `ASIGNATURA` del programa cuyo `semestre_plan` es el nivel siguiente
(`estudiante.semestre_actual + 1`); (2) `PROGRAMA_ACADEMICO` (`semestre_practicas`, `duracion_semestres`, `total_creditos`); (3) un parámetro opcional
`PARAMETRO_SISTEMA` con `clave="plan_estudios"` (tipo JSON) cuando el programa no carga asignaturas:
`{"<programa_id>": {"<nivel>": {"practicas": true, "pasantias": false, "trabajo_grado": false, "creditos": 18, "notas": "..."}}}`.
Si ninguna fuente tiene datos, `fuente = SIN_DATOS` y no hay necesidades.

---

## 2. F10 (RF-34 / RF-35, HU-17)

Estados del F10: `BORRADOR` → `PENDIENTE_APROBACION` (aprobó uno de los dos) → `APROBADO` (aprobaron Bienestar y el Estudiante).
Cualquier cambio a los componentes 1 o 2 tras una aprobación **anula** las aprobaciones (el F10 vuelve a `BORRADOR`, la respuesta trae `advertencias`).
Un F10 `APROBADO` es inmutable (`409 F10_APROBADO_INMUTABLE`).

```json
// F10 (GET /estudiantes/{id}/f10/{f10_id}); F10Resumen = los mismos campos sin los marcados con *
{ "id": 1, "estudiante_id": 5, "semestre_origen": "2026-II", "semestre_destino": "2027-I", "estado": "BORRADOR",
  "plan_id": 12, "evaluacion_id": 4, "trayectoria_id": 2, "plan_siguiente_id": null, "generado_at": "2026-11-16T22:00:00Z",
  "aprobacion_bienestar": { "usuario_id": null, "nombre": null, "aprobado_at": null },
  "aprobacion_estudiante": { "usuario_id": null, "nombre": null, "aprobado_at": null }, "aprobado_at": null,
  "comentario_estudiante": null,                      // *
  "actualizacion_plan": { "items": [ Item ], "nuevos_propuestos": ["..."], "observaciones": null },   // *
  "trayectoria": { "...Trayectoria", "resumen": Resumen, "hitos": [Hito] },                           // *
  "necesidades_anticipadas": [ Necesidad ],           // *
  "proyeccion": { "graduacion": {...}, "siguiente_semestre": {...}, "ajuste_manual": {...} },          // *
  "notas": [ Nota ],                                  // * solo las visibles para quien consulta (RF-35)
  "advertencias": [] }                                // *
```

`Item` (decisión por elemento del plan de origen; viene de las `DECISION_PLAN` del F9, `MANTENER` por defecto si no hubo decisión):

```json
{ "elemento": "AJUSTE|ESTRATEGIA|APOYO|PLAN_COMPLETO|NUEVO", "elemento_id": 31, "nombre": "Examen en sala aparte",
  "tipo_decision": "MANTENER|MODIFICAR|RETIRAR|CREAR_NUEVO", "origen_decision": "F9|SIN_DECISION_F9|BIENESTAR", "decision_id": 8,
  "descripcion_cambio": "Examen en sala aparte con 30 minutos extra", "justificacion": null,
  "descripcion_actual": "...", "semaforo": "AMARILLO", "informativo": true }
```
`informativo: true` (APOYO, PLAN_COMPLETO, NUEVO / CREAR_NUEVO) no se puede editar ni se copia al plan siguiente.
`Necesidad`: `{tipo: PRACTICAS|PASANTIAS|TRABAJO_GRADO|OTRA, semestre_estimado, descripcion, apoyos_previstos, origen: PROYECCION|MANUAL}`.

| Método y ruta | Roles | Cuerpo | Respuesta | Errores (`code`) |
|---|---|---|---|---|
| `POST /estudiantes/{id}/f10/borrador` | BIENESTAR | `{semestre_origen?, semestre_destino?}` (por defecto: semestre del último plan / trayectoria y el siguiente) | `201 F10` | `409 F10_YA_EXISTE` (trae `f10_id`), `422 SEMESTRE_ORIGEN_REQUERIDO`, `422 SEMESTRES_INVALIDOS` |
| `GET /estudiantes/{id}/f10` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `[F10Resumen]` (más reciente primero) | |
| `GET /estudiantes/{id}/f10/{f10_id}` | ídem | — | `F10` | `404 F10_NO_ENCONTRADO` |
| `GET /estudiantes/{id}/f10/{f10_id}/actualizacion-plan` | ídem | — | `{f10_id, estado, plan_id, plan_siguiente_id, items, nuevos_propuestos, observaciones}` | |
| `PATCH /estudiantes/{id}/f10/{f10_id}/actualizacion-plan` | BIENESTAR | `{items?: [{elemento: AJUSTE|ESTRATEGIA, elemento_id, tipo_decision: MANTENER|MODIFICAR|RETIRAR, descripcion_cambio? (obligatoria si MODIFICAR), justificacion?}], nuevos_propuestos?: [str], observaciones?}` | `{f10_id, estado, advertencias, items, ...}` | `422 ELEMENTO_NO_PERTENECE_AL_PLAN`, `409 F10_APROBADO_INMUTABLE` |
| `GET /estudiantes/{id}/f10/{f10_id}/trayectoria` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `{f10_id, estado, trayectoria, necesidades_anticipadas, proyeccion}` | |
| `PATCH /estudiantes/{id}/f10/{f10_id}/trayectoria` | BIENESTAR | `{trayectoria?: <PATCH de trayectoria>, necesidades_anticipadas?: [{tipo, semestre_estimado?, descripcion?, apoyos_previstos?}] (reemplaza la lista), proyeccion?: {libre}}` | igual que el GET + `advertencias` | `409 F10_SIN_TRAYECTORIA`, `409 F10_APROBADO_INMUTABLE` |
| `POST /estudiantes/{id}/f10/{f10_id}/aprobar` | BIENESTAR o ESTUDIANTE | `{comentario?}` (solo lo usa el estudiante) | `F10Resumen` + `plan_siguiente` | `409 F10_YA_APROBADO_POR_USTED`, `409 F10_YA_APROBADO`, `403` para otros roles |

`aprobar`: cada actor registra su sello de tiempo (`aprobacion_bienestar`, `aprobacion_estudiante`). Si es el primer sello → `PENDIENTE_APROBACION`
(si aprobó Bienestar se notifica al estudiante). Con el segundo → `APROBADO`, `aprobado_at`, y **se crea el plan del siguiente semestre en `BORRADOR`**
con los ajustes y estrategias DUA `MANTENER`/`MODIFICAR` (los `RETIRAR` no pasan; el ajuste modificado toma `descripcion_cambio`; se copian las respuestas
por categoría; ajustes en estado `PROPUESTO`, estrategias `PLANEADA`) y un hito `CAMBIO_SEMESTRE`. Si ya existe un plan activo para el semestre destino no se
duplica. `plan_siguiente`: `{creado: true, plan_id, ajustes_copiados, estrategias_copiadas, retirados}` o `{creado: false, plan_id|null, motivo}`.
El plan de origen no cambia de estado (el cierre lo hace el flujo F9).

### Notas de continuidad (RF-35; cifradas en reposo)

Estados: `BORRADOR` → `PENDIENTE_APROBACION_ESTUDIANTE` → `APROBADA` | `RECHAZADA` (→ se edita y se reenvía). `destinatario`: `TODOS|DOCENTE|COORDINADOR|BIENESTAR`.
**Solo `APROBADA` llega a nuevos actores.** Visibilidad: Estudiante = todo lo suyo; Bienestar = lo que elaboró, o de estudiantes con `bienestar_asignado_id` = él,
y lo aprobado (`TODOS|BIENESTAR`); Coordinador = solo aprobadas (`TODOS|COORDINADOR`) de su programa; Docente/Familiar/Admin = nunca (`403`; el destinatario `DOCENTE`
se conserva pero no se expone por API). Editar una nota (aprobada, pendiente o rechazada) la devuelve a `BORRADOR` (`advertencia` en la respuesta).
Leer notas queda en auditoría (`ACCESO_NOTAS_CONTINUIDAD`).

```json
// Nota
{ "id": 7, "estudiante_id": 5, "plan_id": 12, "semestre_origen": "2026-II", "semestre_destino": "2027-I", "destinatario": "TODOS",
  "estado": "PENDIENTE_APROBACION_ESTUDIANTE", "contenido": "Prefiere instrucciones escritas...", "elaborada_por_id": 2,
  "elaborada_por_rol": "BIENESTAR", "aprobada_por_estudiante": false, "aprobada_at": null, "motivo_rechazo": null,
  "created_at": "...", "updated_at": "...", "advertencia": null }
```

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `GET /estudiantes/{id}/f10/{f10_id}/notas` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `[Nota]` (solo las visibles) | `403 ACCESO_DENEGADO` |
| `POST /estudiantes/{id}/f10/{f10_id}/notas` | BIENESTAR, ESTUDIANTE (propio) | `{contenido (3-8000), destinatario?="TODOS"}` | `201 Nota` (`BORRADOR`) | `403` |
| `PATCH /estudiantes/{id}/f10/{f10_id}/notas/{nota_id}` | BIENESTAR (visible), ESTUDIANTE (solo las suyas) | `{contenido?, destinatario?}` | `Nota` (vuelve a `BORRADOR`) | `404 NOTA_NO_ENCONTRADA`, `403` |
| `DELETE /estudiantes/{id}/f10/{f10_id}/notas/{nota_id}` | ídem | — | `{detail}` (soft delete) | |
| `POST .../notas/{nota_id}/enviar` | BIENESTAR | — | `Nota` (`PENDIENTE_APROBACION_ESTUDIANTE`; notifica al estudiante) | `409 NOTA_ESTADO_INVALIDO` |
| `POST .../notas/{nota_id}/aprobar` | ESTUDIANTE | — | `Nota` (`APROBADA`, `aprobada_at`) | `409 NOTA_ESTADO_INVALIDO` (solo si está pendiente, o es un borrador redactado por él mismo) |
| `POST .../notas/{nota_id}/rechazar` | ESTUDIANTE | `{motivo (3-2000)}` | `Nota` (`RECHAZADA`) | `409 NOTA_ESTADO_INVALIDO` |
| `GET /estudiantes/{id}/notas-continuidad?semestre_destino=2027-I` | BIENESTAR, COORDINADOR, ESTUDIANTE | — | `[Nota]` aprobadas para ese semestre, según el alcance del rol | |

### Integraciones (servicios Python para otros slices)

* `app.services.f10.contexto_para_f3(db, estudiante_id, "2027-I") -> dict | None` — contexto inicial del F3 desde el F10 APROBADO (decisiones por nombre,
  trayectoria resumida, necesidades, `escenarios_sugeridos` (siempre AULA y CAMPUS + los de prácticas/pasantías/asignaturas), `plan_siguiente_id`,
  número de notas aprobadas; **nunca** texto de notas ni datos clínicos).
* `app.services.f10.estudiantes_en_practicas(db, semestre, anticipacion=0)` / `notificar_semestre_practicas(db, semestre, anticipacion=0) -> int` — para
  `run_daily_jobs` (evento `SEMESTRE_PRACTICAS` a Bienestar; idempotente con `dedupe_key`; `anticipacion=1` incluye a quienes lo inician el semestre siguiente).
* `app.services.familiar.notificar_seguimiento(db, estudiante_id, corte, semestre)` — avisa a los familiares con alcance `NOTIFICACIONES` (el slice de
  seguimiento debe llamarla al registrar un corte; sin commit).

---

## 3. Panel del Docente (HU-23 / HU-24, D10)

Solo rol `DOCENTE`. Ve únicamente ajustes y estrategias DUA de **sus** asignaturas (`ASIGNACION_DOCENTE`) o donde es responsable, de planes `APROBADO`,
`IMPLEMENTACION`, `SEGUIMIENTO` o `FINALIZADO` (para registrar, no `FINALIZADO`). **Nunca** AQ-10, F1, F2, barreras, diagnóstico, justificación del ajuste,
comentarios/percepción del estudiante, notas de continuidad, nombre, correo ni id del estudiante (los esquemas de salida son lista blanca).

**Seudonimización.** El estudiante aparece como `alias`: «Estudiante K7MQ» (HMAC por docente+estudiante: estable, distinto para cada docente, no reversible).
Parámetro del sistema `docente_ve_nombre` (default `false`): si es `true` se agrega `iniciales` («Z.Q.M.»); el nombre completo nunca se expone.

Un ajuste/estrategia de otra asignatura responde `404 AJUSTE_NO_ENCONTRADO` / `404 ESTRATEGIA_NO_ENCONTRADA` (no revela que existe).

| Método y ruta | Cuerpo | Respuesta | Errores |
|---|---|---|---|
| `GET /docente/mis-ajustes` | — | `MisAjustes` | |
| `GET /docente/ajustes/{id}` | — | `AjusteDetalle` | `404 AJUSTE_NO_ENCONTRADO` |
| `POST /docente/ajustes/{id}/implementacion` | `{implementado: bool, fecha, nota?}` | `201 Implementacion` | `404 AJUSTE_NO_ENCONTRADO`, `422 FECHA_FUTURA`, `409 PLAN_NO_IMPLEMENTABLE` (plan FINALIZADO) |
| `GET /docente/ajustes/{id}/implementacion` | — | `[Implementacion]` (propias, más reciente primero) | `404` |
| `POST /docente/estrategias/{id}/implementacion` | `{estado: INICIADA|IMPLEMENTADA, fecha?, nota?}` | `EstrategiaImplementacion` | `404 ESTRATEGIA_NO_ENCONTRADA`, `409 TRANSICION_ESTRATEGIA_INVALIDA` (solo avanza PLANEADA→INICIADA→IMPLEMENTADA), `422 FECHA_FUTURA`, `409 PLAN_NO_IMPLEMENTABLE` |
| `GET /docente/semaforo` | — | `{resumen: {VERDE, AMARILLO, ROJO, SIN_REGISTRO}, ajustes: [{ajuste_id, nombre_ajuste, alias, asignatura, semaforo_actual, cortes: [{corte, semaforo, implementado}]}]}` | |

```json
// MisAjustes
{ "docente_ve_nombre": false, "total_ajustes": 1, "total_estrategias": 1,
  "asignaturas": [ { "asignatura": { "id": 1, "codigo": "ENF101", "nombre": "Fundamentos de Enfermería" },   // null = ajustes donde es responsable sin asignatura
      "estudiantes": [ { "alias": "Estudiante K7MQ", "iniciales": null,
          "ajustes": [ { "id": 31, "nombre_ajuste": "Ubicación cerca de la puerta", "descripcion": "Puede sentarse junto a la salida",
              "tipo_ajuste": "AMBIENTE", "categorias": ["ESPACIO_TRANQUILO"], "frecuencia": "Cada clase",
              "indicador_efectividad": "Entrega a tiempo", "actividad_si_aplica": null, "fecha_inicio": "2026-08-24",
              "fecha_fin_prevista": null, "permanencia_indefinida": true, "estado": "ACTIVO", "semaforo_actual": "AMARILLO",
              "semestre": "2026-II", "plan_estado": "IMPLEMENTACION", "es_responsable": true,
              "ultima_implementacion": { "id": 4, "fecha": "2026-11-10", "implementado": true, "nota": "Se aplicó en el parcial" } } ],
          "estrategias_dua": [ { "id": 5, "nombre_estrategia": "Material anticipado", "descripcion": "...",
              "dimension_dua": "MULTIPLES_MEDIOS_PRESENTACION", "alcance": null, "escenario": "AULA",
              "estado_implementacion": "PLANEADA", "implementada": false, "nota_implementacion": null, "implementada_at": null,
              "semestre": "2026-II", "plan_estado": "IMPLEMENTACION" } ] } ] } ] }

// AjusteDetalle = el objeto de ajuste anterior + { "alias", "iniciales", "asignatura": {...}|null, "cortes": [{ "corte": "C1", "semaforo": "ROJO", "implementado": true }] }
// Implementacion
{ "id": 4, "ajuste_id": 31, "implementado": true, "fecha": "2026-11-10", "nota": "Se aplicó en el parcial", "registrado_at": "2026-11-10T15:00:00Z" }
// EstrategiaImplementacion
{ "id": 5, "estado_implementacion": "INICIADA", "implementada": false, "nota_implementacion": "Empecé con la unidad 1", "implementada_at": "..." }
```

Registro de implementación: crea `IMPLEMENTACION_APOYO` + `REGISTRO_IMPLEMENTACION` ligados al `RESPONSABLE_APOYO` del docente. Si la matriz F7 aún no
definió el `APOYO` del ajuste o el docente no figura como responsable, se crean con valores mínimos (cargo «Docente»). `implementado=false` guarda la implementación
como `PENDIENTE`; `true` como `EJECUTADA`. Todo se audita (`IMPLEMENTACION_AJUSTE_REGISTRADA`, `IMPLEMENTACION_ESTRATEGIA_DUA`).

---

## 4. Familiar Autorizado (D9, HU-22 / HU-28, Ley 1996/2019)

### 4.1 El Estudiante gestiona autorizaciones (rol ESTUDIANTE, con F0)

`alcance` granular: `{plan, seguimiento, caracterizacion (F1-F2), notificaciones}` (bool; al menos uno `true`). `vigencia_hasta` (fecha) opcional: vence al
final de ese día.

```json
// Autorizacion
{ "id": 3, "familiar_nombre": "Marta Pérez", "familiar_email": "marta@example.com", "parentesco": "Madre",
  "alcance": { "plan": true, "seguimiento": true, "caracterizacion": false, "notificaciones": true },
  "estado": "PENDIENTE|VIGENTE|REVOCADA|EXPIRADA", "cuenta_activada": false, "otorgada_at": "...", "vigencia_hasta": null,
  "revocada_at": null, "motivo_revocacion": null }
```
`estado`: `PENDIENTE` hasta que el familiar activa su cuenta (el token de 72 h llega por correo; al activarla pasa a `VIGENTE`); `EXPIRADA` se calcula si
venció `vigencia_hasta`.

| Método y ruta | Cuerpo | Respuesta | Errores |
|---|---|---|---|
| `POST /estudiantes/mi/familiares` | `{nombre, email, parentesco?, alcance: {plan?, seguimiento?, caracterizacion?, notificaciones?}, vigencia_hasta?}` | `201 Autorizacion` | `422 ALCANCE_VACIO`, `422 CORREO_PROPIO`, `422 VIGENCIA_INVALIDA`, `409 AUTORIZACION_DUPLICADA`, `409 CORREO_EN_USO` (el correo es de una cuenta que no es de familiar) |
| `GET /estudiantes/mi/familiares?incluir_revocadas=false` | — | `[Autorizacion]` | |
| `PATCH /estudiantes/mi/familiares/{id}` | `{nombre?, parentesco?, alcance?: {parcial}, vigencia_hasta?: fecha\|null}` | `Autorizacion` (el cambio rige de inmediato) | `404 AUTORIZACION_NO_ENCONTRADA`, `409 AUTORIZACION_NO_VIGENTE`, `422 ALCANCE_VACIO` (para cortar todo, revocar) |
| `DELETE /estudiantes/mi/familiares/{id}?motivo=` | — | `Autorizacion` (`REVOCADA`; la fila se conserva) | `404`, `409 AUTORIZACION_YA_REVOCADA` |

Otorgar: crea o reutiliza el usuario `FAMILIAR` (invitación vía `accounts.invite_user` + correo «autorizó» con el alcance), audita
`AUTORIZACION_FAMILIAR_OTORGADA`. **Revocar es inmediato**: la autorización deja de contar en la misma petición y, si el familiar no tiene otras
autorizaciones vivas, su cuenta pasa a `INACTIVO` (`403 CUENTA_INACTIVA` con su token actual) y se cierran sus sesiones; audita `AUTORIZACION_FAMILIAR_REVOCADA`.
Volver a autorizar al mismo correo reactiva la cuenta.

### 4.2 El Familiar lee (rol FAMILIAR, solo lectura)

Sin autorización vigente con ese alcance, o con el estudiante sin F0 vigente: `403 ACCESO_DENEGADO` / `403 ESTUDIANTE_SIN_CONSENTIMIENTO` (siempre 403, aunque
el estudiante no exista). Nunca: AQ-10, notas de continuidad, barreras, diagnóstico, justificaciones. Cualquier `POST/PUT/PATCH/DELETE` bajo `/familiar/...`
→ `403 FAMILIAR_SOLO_LECTURA`; en las demás rutas de escritura → `403 ROL_NO_PERMITIDO`. Los accesos se auditan (`ACCESO_FAMILIAR_*`, `ACCESO_CARACTERIZACION`).

| Método y ruta | Alcance requerido | Respuesta |
|---|---|---|
| `GET /familiar/estudiantes` | — | `[{estudiante_id, nombre, parentesco, alcance: {...}, vigencia_hasta, otorgada_at}]` (solo autorizaciones vivas) |
| `GET /familiar/estudiantes/{id}/plan` | `plan` | `{estudiante: {id, nombre}, plan: {semestre, estado, version, vigencia_inicio, vigencia_fin, fecha_aprobacion, resumen_ejecutivo, ajustes: [{id, nombre_ajuste, descripcion, tipo_ajuste, frecuencia, indicador_efectividad, estado, semaforo_actual}], estrategias_dua: [{id, nombre_estrategia, descripcion, dimension_dua, estado_implementacion}], firmas: [{rol, firmado_at}]}}` del último plan aprobado/vigente; `404 PLAN_NO_DISPONIBLE` si aún no hay |
| `GET /familiar/estudiantes/{id}/seguimiento` | `seguimiento` | `{estudiante, semestre, cortes: [{corte, fecha_seguimiento, semaforo_estado, cerrado, ajustes: [{nombre_ajuste, semaforo, implementado}]}]}` (sin narrativas ni percepción); `404 PLAN_NO_DISPONIBLE` |
| `GET /familiar/estudiantes/{id}/caracterizacion` | `caracterizacion` | `{estudiante, caracterizacion: {fecha_caracterizacion, resumen_ejecutivo, autodescripcion_estudiante, comunicacion[], sensorial[], autonomia[], preferencias[]} \| null, fortalezas: {narrativas, fortalezas[], intereses[], estrategias[]} \| null}` (sin diagnóstico ni AQ-10) |

Las notificaciones de seguimiento (`notificaciones: true`) llegan a la bandeja normal del familiar (`NOTIFICACION`, evento `SEGUIMIENTO_FAMILIAR`, push + correo).

---

## Cambios de esquema / catálogos

* Migración `00C3` (down_revision `0001`): tabla nueva `f10_semestre` (cabecera del F10, doble aprobación, decisiones del plan, proyección).
* `AlcanceFamiliar.NOTIFICACIONES` (valor nuevo dentro de una lista JSON; sin cambio de esquema).
* `services/notifications.py`: eventos `F10_PENDIENTE_APROBACION` y `SEGUIMIENTO_FAMILIAR` (+ plantillas).
