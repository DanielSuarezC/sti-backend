# Slice C2 — Seguimiento F8 (semáforo), Evaluación F9, tablero de estudiantes y «Mi ruta»

Prefijo `/api/v1`. Autenticación `Authorization: Bearer <jwt>` (ver `auth.md`). Errores: `{"detail": "<español>", "code": "SNAKE_CASE"}`
(422 agrega `errores:[{campo,mensaje}]`). Fechas ISO-8601. Los cuerpos de entrada **rechazan campos desconocidos** (422 `DATOS_INVALIDOS`).
Todo estudiante-dato exige F0 firmado (403 `ESTUDIANTE_SIN_CONSENTIMIENTO` para el staff; 403 `CONSENTIMIENTO_REQUERIDO` para el estudiante),
salvo `mi-ruta`, `{id}/ruta`, `{id}/pendientes` y `{id}` (muestran solo estados).

Enums: `corte` `C1|C2|C3` · `semaforo` `VERDE|AMARILLO|ROJO` · `percepcion` `POSITIVA|PARCIAL|NEGATIVA` · `estado` de corte `FUTURO|ABIERTO|CERRADO` ·
`estado_seguimiento` (derivado del ajuste en el corte) `EFECTIVO|CONCERTACION_ABIERTA|CONCERTACION_RESUELTA|REQUIERE_REDISENO|REDISENO_REGISTRADO|null` ·
`tendencia` `MEJORA|EMPEORA|ESTABLE|SIN_DATOS` · `tipo_registro` `ENTREVISTA|OBSERVACION|CUESTIONARIO|FORMULARIO|NOTA` ·
`tipo_evidencia` `ACADEMICA|CONDUCTUAL|SOCIAL|EMOCIONAL|PARTICIPACION|ASISTENCIA` ·
`dimension_resultado` `ACCESO|PARTICIPACION|APRENDIZAJE|BIENESTAR|AUTONOMIA|PERMANENCIA|PROGRESION|GRADUACION|TRANSICION` ·
`tipo_decision` `MANTENER|MODIFICAR|RETIRAR|CREAR_NUEVO` · `nivel`/`efectividad_general` `BAJA|MEDIA|ALTA` · `estado` F9 `BORRADOR|CERRADA`.

## 1. Reglas del semáforo (la lógica vive solo en el backend)

| Semáforo | Qué hace el sistema |
|---|---|
| **VERDE** | Mantener. El ajuste queda `estado_seguimiento = "EFECTIVO"` (alimenta trayectoria, F9 y CBR). Si pasa de AMARILLO a VERDE, la tarea de concertación abierta se cancela. |
| **AMARILLO** | Crea la **tarea de concertación** (Bienestar + estudiante) con `fecha_limite` = fecha del siguiente corte (en C3: fin del semestre). Persistencia: JSON `tarea_concertacion` del registro del ajuste + notificación `tipo = "TAREA_CONCERTACION"` (solo push) a Bienestar y estudiante. Se resuelve con `POST …/concertacion`. |
| **ROJO** | **Notificación inmediata push + correo a exactamente 4 actores (RF-39 / D11)**: el profesional de Bienestar del estudiante (asignado → elaborador del plan → quien registra), el/los Coordinador(es) **del programa del estudiante**, el docente responsable del ajuste (`responsable_id`; si no hay, los docentes asignados a su asignatura) y el estudiante. Evento `AJUSTE_SEMAFORO_ROJO`. Dedupe: una notificación por (registro del ajuste, usuario): reenviar o volver a ROJO sobre el mismo registro no repite. El ajuste queda `REQUIERE_REDISENO` y **bloquea abrir el siguiente corte** (`409 REDISENO_PENDIENTE`) hasta registrar el rediseño. En C2 el rediseño es obligatorio (v7 §7.2); se aplica igual a C1. En C3: el F9 no admite `MANTENER` para un ajuste cuyo último semáforo es ROJO (`422 DECISION_INCOMPATIBLE_ROJO`). |

Notas: reenviar el mismo semáforo no cambia nada (no audita ni notifica). Todo cambio de semáforo se audita (`CAMBIO_SEMAFORO` con `de`, `a`, `ajuste_id`, `corte`, actor).
`AMARILLO`/`ROJO` exigen `resultado_observado` (422 `RESULTADO_OBSERVADO_REQUERIDO`). El ajuste en estado «REQUIERE_REDISENO» se expone como `estado_seguimiento` (el enum `EstadoAjuste` del plan no cambia).
Cachés mantenidos: `ajuste.semaforo_actual` (último corte valorado), `plan.semaforo_actual` (el peor de los ajustes), `seguimiento.semaforo_estado`.

## 2. Seguimiento F8 (`/planes/{plan_id}/seguimiento…`)

Roles: lectura Bienestar, Coordinador (su programa), Estudiante (propio), Docente (solo sus ajustes y vista reducida), Familiar (si autorizó `SEGUIMIENTO`); Admin → 403.
Escritura solo Bienestar; percepción solo el estudiante (HU-21). Los cortes salen del `CALENDARIO_ACADEMICO` activo (→ `409 CALENDARIO_NO_CONFIGURADO` si no hay).

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET /planes/{id}/seguimiento` | B, Co, D*, E, F | Cortes con estado. |
| `POST /planes/{id}/seguimiento/{corte}` | B | Crea (**201**) o devuelve (**200**) el seguimiento. Cuerpo opcional `SeguimientoAbrir`. |
| `GET /planes/{id}/seguimiento/{corte}` | B, Co, D*, E, F | Detalle del corte. |
| `PATCH /planes/{id}/seguimiento/{corte}` | B | Edita la cabecera (corte abierto). |
| `POST /planes/{id}/seguimiento/{corte}/cerrar` | B | Cierra el corte (todos los ajustes con semáforo). |
| `PUT /planes/{id}/seguimiento/{corte}/ajustes/{ajuste_id}` | B | Registro por ajuste + semáforo. |
| `PUT …/ajustes/{ajuste_id}/percepcion` | **solo E** | Percepción del estudiante. |
| `POST …/ajustes/{ajuste_id}/concertacion` | B | Resuelve la tarea de concertación (AMARILLO). |
| `POST …/ajustes/{ajuste_id}/rediseno` | B | Registra el rediseño (ROJO). Corte abierto o cerrado. |
| `POST …/registros` · `DELETE …/registros/{id}` | B | `REGISTRO_SEGUIMIENTO` (entrevista, observación…). 201 / soft delete. |
| `POST …/evidencias` · `DELETE …/evidencias/{id}` | B | `EVIDENCIA_EFECTIVIDAD` + `RESULTADO_INDICADOR` por dimensión. 201 / soft delete. |
| `POST …/barreras-emergentes` | B | Crea `BARRERA_IDENTIFICADA` y deja la propuesta de ajuste. 201. |
| `GET /planes/{id}/semaforo` | B, Co, D*, E, F | Dashboard: matriz ajuste × corte, tendencia, % verde, indicadores. |

(*) Docente: vista reducida (ver abajo). B=Bienestar, Co=Coordinador, D=Docente, E=Estudiante, F=Familiar.

### `GET /planes/{id}/seguimiento` → 200
```json
{ "plan_id": 12, "plan_estado": "SEGUIMIENTO", "semestre": "2026-II",
  "calendario": {"id": 1, "semestre_academico": "2026-II", "programa_id": null},
  "cortes": [
    {"corte": "C1", "fecha_corte": "2026-09-23", "estado": "CERRADO", "seguimiento_id": 5, "cerrado": true, "vencido": false,
     "dias_restantes": -54, "semaforo_estado": "ROJO", "resumen": {"VERDE": 1, "AMARILLO": 1, "ROJO": 1, "SIN_VALORAR": 0, "total": 3},
     "puede_abrir": false, "bloqueo": null},
    {"corte": "C2", "fecha_corte": "2026-10-28", "estado": "FUTURO", "seguimiento_id": null, "cerrado": false, "vencido": true,
     "dias_restantes": -19, "semaforo_estado": null, "resumen": null, "puede_abrir": false,
     "bloqueo": {"code": "REDISENO_PENDIENTE", "detail": "Hay ajustes en ROJO sin rediseño registrado…", "ajuste_ids": [31]}},
    {"corte": "C3", "estado": "FUTURO", "…": "…"} ],
  "rojos_sin_rediseno": [31] }
```
`bloqueo.code` ∈ `PLAN_NO_EN_SEGUIMIENTO | CORTE_ANTERIOR_ABIERTO | REDISENO_PENDIENTE`. `vencido`: la fecha del corte ya pasó y no se abrió.

### `POST /planes/{id}/seguimiento/{corte}`
Cuerpo (todo opcional): `{fecha_seguimiento, participantes_ids:[int], descripcion_situacion_actual, funcionamiento_apoyos, dificultades_emergentes, ajustes_recomendados, observaciones_generales}`.
Solo planes en `IMPLEMENTACION` o `SEGUIMIENTO`; al abrir el primer corte el plan pasa a `SEGUIMIENTO`. Respuesta: detalle del corte (abajo).
Errores: `409 CALENDARIO_NO_CONFIGURADO | PLAN_NO_EN_SEGUIMIENTO | CORTE_ANTERIOR_ABIERTO | REDISENO_PENDIENTE | CORTE_CERRADO`, `422` (corte distinto de C1/C2/C3).

### Detalle del corte (`GET …/{corte}`, y respuesta de POST/PATCH)
```json
{ "seguimiento_id": 5, "plan_id": 12, "corte": "C1", "cerrado": false, "estado": "ABIERTO", "fecha_seguimiento": "2026-09-24",
  "fecha_proximo_seguimiento": "2026-10-28", "semaforo_estado": "ROJO", "version_plan": 1, "profesional_responsable_id": 3,
  "participantes_ids": [3, 9], "descripcion_situacion_actual": "…", "funcionamiento_apoyos": null, "dificultades_emergentes": "…",
  "ajustes_recomendados": null, "observaciones_generales": null,
  "resumen": {"VERDE": 1, "AMARILLO": 1, "ROJO": 1, "SIN_VALORAR": 0, "total": 3},
  "ajustes": [ {"ajuste_id": 30, "nombre_ajuste": "Ubicación…", "tipo_ajuste": "AMBIENTE", "asignatura_id": 1, "responsable_id": 4,
                "registro": { /* Registro, ver abajo; null si aún no hay */ } } ],
  "registros": [{"id": 1, "tipo_registro": "ENTREVISTA", "descripcion_metodologia": "…", "fuentes_informacion": null, "created_at": "…"}],
  "evidencias": [{"id": 1, "tipo_evidencia": "ACADEMICA", "descripcion_evidencia": "…", "fuente_evidencia": null, "dato_cuantitativo": 4.1,
                  "periodo_medicion": null, "resultados": [{"id": 1, "dimension_resultado": "APRENDIZAJE", "indicador_especifico": "…",
                  "valor_logrado": null, "meta_establecida": null, "porcentaje_cumplimiento": 82, "interpretacion": null}]}],
  "barreras_emergentes": [{"barrera_id": 9, "tipo_barrera": "SENSORIAL", "ajuste_id": 30, "propuesta_ajuste": {…}, "fecha": "2026-09-25"}],
  "rojos_sin_rediseno": [31] }
```
**Registro** (objeto por ajuste y corte):
```json
{ "id": 7, "seguimiento_id": 5, "ajuste_id": 30, "corte": "C1", "semaforo": "AMARILLO", "estado_seguimiento": "CONCERTACION_ABIERTA",
  "implementado": true, "frecuencia_implementacion": "Todas las clases", "comentario_docente": null,
  "semaforo_cambiado_at": "2026-09-24T15:00:00Z", "resultado_observado": "…", "percepcion_estudiante": "NEGATIVA",
  "comentario_estudiante": "…", "nueva_barrera_detectada": null,
  "tarea_concertacion": {"estado": "ABIERTA", "corte_origen": "C1", "fecha_limite": "2026-10-28", "asignada_a": ["BIENESTAR","ESTUDIANTE"],
                         "creada_at": "…", "acuerdo": null, "resuelta_at": null},
  "rediseno": null }
```
`semaforo` puede ser `null` (el estudiante escribió su percepción antes de que Bienestar valorara). `rediseno` (tras registrarlo):
`{"decision":"MODIFICAR","descripcion":"…","concertado_con_estudiante":true,"nueva_version_plan":null,"registrado_at":"…","registrado_por_id":3}`.
**Vista Docente** (`GET` corte / semáforo): solo los ajustes que le corresponden, sin `descripcion_situacion_actual`, `registros`, `evidencias`, `barreras_emergentes` ni, en el registro, `resultado_observado`, percepción, comentarios del estudiante, tarea ni rediseño (quedan: `semaforo`, `estado_seguimiento`, `implementado`, `frecuencia_implementacion`, `comentario_docente`).

### `PUT …/ajustes/{ajuste_id}` (Bienestar)
Cuerpo: `{semaforo?, implementado?: bool, frecuencia_implementacion?: str, resultado_observado?: str}` (**no** acepta percepción: 422). Corte abierto.
```json
{ "registro": { /* Registro */ },
  "semaforo": {"cambio": true, "anterior": null, "nuevo": "ROJO", "notificados": ["BIENESTAR","COORDINADOR","DOCENTE","ESTUDIANTE"],
               "tarea_concertacion": null, "requiere_rediseno": true, "advertencias": []} }
```
`advertencias`: p. ej. VERDE con percepción NEGATIVA del estudiante (no bloquea). Errores: `404 CORTE_NO_ABIERTO | AJUSTE_NO_ENCONTRADO`, `409 CORTE_CERRADO`, `422 RESULTADO_OBSERVADO_REQUERIDO`.

### `PUT …/ajustes/{ajuste_id}/percepcion` (solo el estudiante dueño del plan)
Cuerpo `{percepcion, comentario?}` → `{"registro": {…}}`. Puede corregirla mientras el corte esté abierto. Bienestar, docente, coordinador, otro estudiante, familiar: `403`.
Errores: `404 CORTE_NO_ABIERTO`, `409 CORTE_CERRADO`.

### `POST …/ajustes/{ajuste_id}/concertacion` — cuerpo `{acuerdo}` (5–3000) → `{"registro"}`. Errores `409 SIN_TAREA_CONCERTACION | CONCERTACION_YA_RESUELTA`, `404 REGISTRO_NO_ENCONTRADO`.
### `POST …/ajustes/{ajuste_id}/rediseno` — cuerpo `{decision: MODIFICAR|REEMPLAZAR|RETIRAR, descripcion (10–3000), concertado_con_estudiante?: bool, nueva_version_plan?: int}`
→ `{"registro": {…}, "rojos_sin_rediseno": [ids]}`. Solo si el semáforo es ROJO (`409 AJUSTE_NO_ESTA_EN_ROJO`). No cambia el plan: la modificación formal la hace el flujo de planes (nueva versión).

### `POST …/cerrar`
Exige semáforo en TODOS los ajustes (`409 AJUSTES_SIN_SEMAFORO`, con `ajuste_ids`). Respuesta:
```json
{ "semaforo_agregado": "ROJO", "rojos_sin_rediseno": [31],
  "siguiente_paso": {"titulo": "Registre el rediseño de los ajustes en ROJO", "descripcion": "…", "ruta_frontend": "/bienestar/estudiantes/8/seguimiento"},
  "corte": { /* detalle del corte */ } }
```
En C3 el `siguiente_paso` apunta al F9.

### `POST …/registros` (201) `{tipo_registro, descripcion_metodologia?, fuentes_informacion?}` → `{id, tipo_registro, descripcion_metodologia, fuentes_informacion}`
### `POST …/evidencias` (201) `{tipo_evidencia, descripcion_evidencia, fuente_evidencia?, dato_cuantitativo?: number, periodo_medicion?, resultados?: [{dimension_resultado, indicador_especifico, valor_logrado?, meta_establecida?, porcentaje_cumplimiento?: 0-100, interpretacion?}]}` → la evidencia (forma de arriba).
`DELETE` de ambos: soft delete, `{"detail": "… archivada."}`, `404 REGISTRO_NO_ENCONTRADO | EVIDENCIA_NO_ENCONTRADA`.

### `POST …/barreras-emergentes` (201)
Cuerpo: `{tipo_barrera, escenario?, descripcion_barrera, severidad?: LEVE|MODERADA|SEVERA, frecuencia?, ajuste_id?, propuesta_ajuste?: {nombre_ajuste, descripcion_ajuste, justificacion, tipo_ajuste}, propuesta_respuesta_institucional?}`.
Para `tipo_barrera = "SOCIAL"` la propuesta institucional es obligatoria (RF-19, `422 PROPUESTA_INSTITUCIONAL_REQUERIDA`).
```json
{ "barrera_id": 9, "tipo_barrera": "SENSORIAL", "propuesta_ajuste": {"nombre_ajuste": "…", "descripcion_ajuste": "…", "justificacion": "…", "tipo_ajuste": "AMBIENTE"},
  "siguiente_paso": {"titulo": "Actualice el plan con el ajuste propuesto", "descripcion": "…", "ruta_frontend": "/bienestar/estudiantes/8/plan"} }
```
La barrera queda en el F4 (`IDENTIFICADA`); la propuesta se anota en el corte (`ajustes_recomendados`, `barreras_emergentes`) y en `nueva_barrera_detectada` del ajuste. No modifica el plan (eso es del flujo de planes).

### `GET /planes/{id}/semaforo`
```json
{ "plan_id": 12, "plan_estado": "SEGUIMIENTO", "semestre": "2026-II", "cortes": ["C1","C2","C3"],
  "fechas_cortes": {"C1": "2026-09-23", "C2": "2026-10-28", "C3": "2026-12-01"},
  "ajustes": [ {"ajuste_id": 30, "nombre_ajuste": "…", "tipo_ajuste": "AMBIENTE", "asignatura_id": 1, "responsable_id": 4,
                "semaforo_actual": "VERDE", "tendencia": "MEJORA", "estado_seguimiento": "EFECTIVO",
                "cortes": {"C1": {/* Registro */}, "C2": {/* Registro */}, "C3": null}} ],
  "resumen": {"por_corte": {"C1": {"VERDE": 1, "AMARILLO": 1, "ROJO": 0, "SIN_VALORAR": 0, "total": 2, "valorados": 2, "porcentaje_verde": 50.0}, "C2": {…}, "C3": {…}},
              "semaforo_agregado": "AMARILLO", "porcentaje_verde_actual": 50.0, "total_ajustes": 2,
              "ajustes_efectivos": [30], "requieren_rediseno": []},
  "tendencia": {"cortes": ["C1","C2","C3"], "escala": {"VERDE": 0, "AMARILLO": 1, "ROJO": 2},
                "series": [{"ajuste_id": 30, "nombre_ajuste": "…", "tendencia": "MEJORA", "semaforos": ["AMARILLO","VERDE",null], "valores": [1,0,null]}],
                "agregado": [{"corte": "C1", "VERDE": 1, "AMARILLO": 1, "ROJO": 0, "SIN_VALORAR": 0, "porcentaje_verde": 50.0}]},
  "indicadores": {"D6": {"indicador": "D6", "valor": 100.0, "implementados": 2, "total": 2, "meta": 80, "cumple": true, "corte_referencia": "C2", "datos_suficientes": true},
                  "D8": {"indicador": "D8", "valor": 50.0, "verdes": 1, "total": 2, "meta": 80, "cumple": false, "corte_referencia": "C3", "datos_suficientes": false}} }
```
`fechas_cortes` es `null` si no hay calendario. Docente: sin `indicadores`, solo sus ajustes y registros de vista reducida. `datos_suficientes=false` = indicador provisional (aún no hay datos del corte de referencia).
`tendencia` por ajuste: compara los dos últimos semáforos valorados (menor es mejor).

## 3. Evaluación F9 (`/planes/{plan_id}/evaluacion…`)

Roles: lectura Bienestar, Coordinador, Estudiante; escritura solo Bienestar. Docente, Familiar y Admin: 403 (§12.1).

| Método y ruta | Roles | Descripción |
|---|---|---|
| `POST /planes/{id}/evaluacion` | B | **201** borrador consolidado C1+C2+C3. |
| `GET /planes/{id}/evaluacion` | B, Co, E | Formulario + síntesis + tendencia + bloqueos de cierre. |
| `PATCH /planes/{id}/evaluacion` | B | Guarda decisiones, valoración de las 9 dimensiones y textos. |
| `DELETE /planes/{id}/evaluacion/decisiones/{decision_id}` | B | Archiva (soft delete) una decisión del borrador. |
| `GET /planes/{id}/evaluacion/tendencia` | B, Co, E | Datos del gráfico C1→C2→C3 (igual que `tendencia` del dashboard). |
| `POST /planes/{id}/evaluacion/cerrar` | B | Cierra el F9: plan → `FINALIZADO`, alimenta CBR. |

**POST** (sin cuerpo). Requiere plan en `IMPLEMENTACION|SEGUIMIENTO` (`409 PLAN_NO_EN_SEGUIMIENTO`), al menos un corte abierto (`409 SIN_SEGUIMIENTO`) y que no exista otra evaluación (`409 EVALUACION_YA_EXISTE`). Consolida lo disponible (el borrador puede crearse con solo C1); se recalcula en cada `GET` mientras es `BORRADOR`.

**PATCH** `EvaluacionPatch` (todo opcional):
```json
{ "efectividad_general": "MEDIA", "nuevas_barreras_identificadas": "…", "fortalezas_emergentes": "…", "cambios_contexto": "…",
  "recomendaciones": "…", "lecciones_aprendidas": "…",
  "valoracion_dimensiones": {"ACCESO": {"nivel": "ALTA", "comentario": "…"}, "PARTICIPACION": {"nivel": "MEDIA"}},
  "decisiones": [ {"ajuste_id": 30, "tipo_decision": "MANTENER", "justificacion": "Verde en los tres cortes", "lecciones_aprendidas": "…"},
                  {"ajuste_id": 31, "tipo_decision": "RETIRAR", "justificacion": "Rojo en C3"},
                  {"tipo_decision": "CREAR_NUEVO", "descripcion_decision": "Guía visual", "justificacion": "Reemplaza al retirado"} ] }
```
Las decisiones se **upsertan** por ajuste (para `CREAR_NUEVO`, por `descripcion_decision`); `valoracion_dimensiones` se fusiona. `justificacion` obligatoria (5–3000).
Errores: `422 AJUSTE_REQUERIDO | DESCRIPCION_REQUERIDA | DECISION_DUPLICADA | DECISION_INCOMPATIBLE_ROJO | DATOS_INVALIDOS`, `404 AJUSTE_NO_ENCONTRADO | EVALUACION_NO_ENCONTRADA`, `409 EVALUACION_CERRADA`.

**GET / respuesta de POST, PATCH**:
```json
{ "id": 3, "plan_id": 12, "estado": "BORRADOR", "fecha_evaluacion": "2026-12-02", "evaluador_id": 3, "periodo_evaluacion": "2026-II",
  "efectividad_general": "MEDIA", "evidencias_resumidas": "Consolidado de seguimiento. C1: 1 verde, …", "apoyos_efectivos": null,
  "apoyos_requieren_ajuste": null, "apoyos_a_discontinuar": null, "nuevas_barreras_identificadas": null, "fortalezas_emergentes": null,
  "cambios_contexto": null, "recomendaciones": null, "lecciones_aprendidas": null, "alimento_cbr": false, "cerrada_at": null,
  "valoracion_dimensiones": {"ACCESO": {"nivel": "ALTA", "comentario": "ok"}},
  "decisiones": [{"id": 1, "ajuste_id": 30, "tipo_decision": "MANTENER", "elemento_afectado": "AJUSTE", "descripcion_decision": "MANTENER el ajuste «…»",
                  "justificacion": "…", "lecciones_aprendidas": "…", "estado_decision": "PROPUESTA", "fecha_implementacion_decision": null}],
  "sintesis": {
    "plan_id": 12, "semestre": "2026-II",
    "cortes": [{"corte": "C1", "estado": "CERRADO", "VERDE": 1, "AMARILLO": 0, "ROJO": 1, "SIN_VALORAR": 0, "porcentaje_verde": 50.0}],
    "ajustes": [{"ajuste_id": 30, "nombre_ajuste": "…", "tipo_ajuste": "AMBIENTE", "tendencia": "ESTABLE", "semaforo_final": "VERDE",
                 "tasa_implementacion": 100.0, "decision_sugerida": "MANTENER", "motivo_sugerencia": "El último semáforo es VERDE…",
                 "evolucion": [{"corte": "C1", "semaforo": "VERDE", "implementado": true, "frecuencia_implementacion": "…", "resultado_observado": "…",
                                "percepcion": "POSITIVA", "comentario_estudiante": "…", "estado_seguimiento": "EFECTIVO"}]}],
    "indicadores": {"D6": {…}, "D8": {…}},
    "evidencias": [{"corte": "C1", "id": 1, "tipo_evidencia": "ACADEMICA", "…": "…", "resultados": [{…}]}],
    "dimensiones": {"APRENDIZAJE": {"promedio_cumplimiento": 82.0, "n_indicadores": 1, "nivel_sugerido": "ALTA"}, "ACCESO": {"promedio_cumplimiento": null, "n_indicadores": 0, "nivel_sugerido": null}},
    "barreras_emergentes": [], "efectividad_general_sugerida": "MEDIA" },
  "tendencia": { /* igual que en el dashboard */ },
  "puede_cerrar": false,
  "bloqueos_cierre": [{"code": "DECISIONES_INCOMPLETAS", "detail": "Falta la decisión de: «…»", "ajuste_ids": [31]},
                      {"code": "VALORACION_INCOMPLETA", "detail": "…", "dimensiones": ["GRADUACION"]}] }
```
`decision_sugerida`: VERDE→MANTENER; AMARILLO→MODIFICAR; ROJO→MODIFICAR (RETIRAR si ROJO en cortes consecutivos). `nivel_sugerido`: promedio ≥80 ALTA, ≥50 MEDIA, si no BAJA. `efectividad_general_sugerida` según % verde (D8). Cerrado: `sintesis` queda congelada.

**POST …/cerrar** → `{"cbr": {"creados": 1, "actualizados": 0, "sin_estrategia": 0}, "plan_estado": "FINALIZADO", "evaluacion": {…}}`.
Condiciones (si no, `409` con el `code` del primer bloqueo y `bloqueos` completo): `C3_NO_CERRADO`, `DECISIONES_INCOMPLETAS` (decisión en todos los ajustes activos), `VALORACION_INCOMPLETA` (las 9 dimensiones), `PLAN_NO_EN_SEGUIMIENTO` / `TRANSICION_PLAN_INVALIDA` (máquina de estados). Ya cerrado: `409 EVALUACION_CERRADA`.
Al cerrar: decisiones → `ACORDADA`, textos `apoyos_efectivos/requieren_ajuste/a_discontinuar`, plan → `FINALIZADO`, `alimento_cbr = true`, auditoría.
**CBR**: por cada ajuste cuyo último semáforo es VERDE y su estrategia DUA asociada (misma barrera vía sugerencia; si no, estrategia del catálogo que atiende ese tipo de barrera/escenario) se crea/actualiza un `CASO_CBR` (`origen = "F9"`, `exitoso`, `peso` 1.0 o 0.8 si la percepción no fue positiva). El perfil es anónimo: `{tipos_barrera, escenarios, principios, severidad_max, tipo_ajuste}` (sin nombre, AQ-10, diagnóstico ni IDs de la persona).

## 4. Estudiantes: tablero, resumen, «Mi ruta», pendientes (`/estudiantes…`)

| Método y ruta | Roles | Descripción |
|---|---|---|
| `GET /estudiantes` | B (sus estudiantes), Co (su programa), Admin (todos) | Tablero paginado con filtros. |
| `GET /estudiantes/mi-ruta` | E | Los 12 pasos del propio estudiante. |
| `GET /estudiantes/{id}` | B, Co, Admin, E (propio) | Resumen según el rol. |
| `GET /estudiantes/{id}/ruta` | B, Co, E (propio) | Los 12 pasos. |
| `GET /estudiantes/{id}/pendientes` | B, Co, E (propio) | Pendientes (cada rol ve los suyos; Bienestar, todos). |
| `PUT /estudiantes/{id}/bienestar` | B, Admin | Asigna el profesional de Bienestar. |
| `POST /estudiantes/{id}/inasistencia` | B | Registro manual (RF-31). |
| `GET /estudiantes/{id}/inasistencia` | B, Co, E (propio) | Historial. |
| `POST /estudiantes/{id}/inasistencia/sigaa` | B | Lectura SIGAA (opcional). |

**`GET /estudiantes`** — query: `q` (nombre o código), `estado` (estado de la **cuenta**: `ACTIVO|PENDIENTE_CONSENTIMIENTO|…`), `estado_plan`, `semaforo` (`VERDE|AMARILLO|ROJO|SIN_SEMAFORO`, semáforo agregado del plan vigente), `con_pendientes` (true/false), `asignados_a_mi` (bool), `programa_id`, `page`, `page_size` (≤100). Orden: nombre.
Alcance: Bienestar según `BIENESTAR_SCOPE` (`all` todos / `assigned` asignados o sin asignar); Coordinador: su programa; Admin: todos (solo datos básicos). Docente, Estudiante, Familiar: 403.
```json
{ "items": [ { "id": 8, "usuario_id": 21, "nombre_completo": "Estudiante Cinco (demo)", "codigo_estudiante": "DEMO0005", "programa_id": 1, "programa": "Enfermería",
               "semestre_actual": 1, "estado_cuenta": "ACTIVO", "estado_academico": "ACTIVO", "via_ingreso": "BIENESTAR",
               "bienestar_asignado": {"id": 3, "nombre_completo": "…"},
               "plan": {"id": 12, "estado": "SEGUIMIENTO", "semaforo": "ROJO", "version": 1}, "semaforo_agregado": "ROJO",
               "paso_actual": 1, "progreso": {"hechos": 3, "total": 12}, "pendientes": 4 } ],
  "total": 5, "page": 1, "page_size": 20 }
```
El listado **nunca** incluye AQ-10, F1/F2, diagnóstico ni «lo que sigue» (ver `/pendientes`). `paso_actual` es `null` si falta el F0. Con `con_pendientes` se calcula sobre todo el conjunto filtrado (pilotos de decenas de estudiantes). Admin recibe solo `{id, usuario_id, nombre_completo, codigo_estudiante, programa_id, estado_cuenta, estado_academico}`.

**`GET /estudiantes/{id}`** → fila del tablero + `{email, anio_ingreso, consentimiento_firmado, ruta: {…}}`; Bienestar y el propio estudiante además `telefono`, `contacto_emergencia`, `aq10: {"aplicado": bool, "ruta_activada": bool|null}` (sin puntaje); Coordinador no recibe `aq10`; Admin recibe solo datos básicos (`id, usuario_id, nombre_completo, email, codigo_estudiante, programa_id, anio_ingreso, semestre_actual, estado_cuenta, estado_academico, via_ingreso`).

**`GET …/ruta` y `/mi-ruta`**
```json
{ "estudiante_id": 8, "plan": {"id": 12, "estado": "IMPLEMENTACION", "semaforo": null, "version": 1},
  "previos": [ {"codigo": "F0", "nombre": "Consentimiento informado", "estado": "hecho", "ruta_frontend": "/estudiante/consentimiento"},
               {"codigo": "AQ10", "nombre": "Tamizaje AQ-10", "estado": "hecho", "ruta_frontend": "/estudiante/aq10"} ],
  "pasos": [ {"numero": 1, "nombre": "Conocer al estudiante", "descripcion": "…", "modulo": "M2", "formato": "F1", "estado": "actual",
              "en_curso": false, "detalle": null, "ruta_frontend": "/estudiante/perfil"}, "… 12 pasos …" ],
  "progreso": {"hechos": 3, "total": 12}, "paso_actual": 1, "pendientes": 4, "ruta_activada": true,
  "siguiente": {"titulo": "Completar la caracterización (F1)", "descripcion": "…", "ruta_frontend": "/estudiante/perfil", "codigo": "F1"} }
```
* `previos[AQ10]` y `ruta_activada` solo para Bienestar y Estudiante (el Coordinador no ve nada del AQ-10); `ruta_activada` solo si el AQ-10 fue aplicado.
* `estado`: `hecho` | `actual` (primer paso sin completar, solo si el F0 está firmado) | `pendiente`. `en_curso`: tiene datos parciales. `detalle`: texto breve (p. ej. «C1 cerrado, C2 abierto»).
* Pasos (v7 §8): 1 F1/M2 · 2 F2/M2 · 3 F3/M3 · 4 F4/M4 · 5 F5/M4 · 6 DUA F6/M3 · 7 barreras persistentes F4/M4 · 8 ajustes F6/M5 · 9 apoyos F7/M5 · 10 seguimiento F8/M6 · 11 F9/M7 · 12 F10/M8.
  Completos cuando: 1 caracterización COMPLETA · 2 perfil con ≥1 fortaleza · 3 contexto F3 del semestre del plan · 4 ≥1 barrera · 5 ≥1 facilitador · 6 sugerencias DUA todas decididas · 7 ninguna barrera sin revisar tras el DUA · 8 plan firmado (APROBADO o posterior) · 9 apoyos en la matriz o plan en IMPLEMENTACION+ · 10 C3 cerrado · 11 F9 cerrada · 12 nota de continuidad aprobada.
* `siguiente` = primer pendiente del rol que consulta; si no hay, «Estamos trabajando en el paso N» (el estudiante no tiene acción) o «Recorrido completo».
* **Mi ruta** no exige F0: sin firmar, `siguiente` lleva a `/estudiante/consentimiento`.

**`GET …/pendientes`** → `{"estudiante_id": 8, "total": 3, "items": [...]}`. Cada ítem:
```json
{ "codigo": "REDISENO_PENDIENTE", "titulo": "Registrar el rediseño de un ajuste en ROJO", "descripcion": "Bloquea el siguiente corte.",
  "responsables": ["BIENESTAR"], "prioridad": "ALTA", "ruta_frontend": "/bienestar/estudiantes/8/seguimiento",
  "plan_id": 12, "ajuste_id": 31, "corte": "C1", "fecha_limite": null }
```
`codigo` ∈ `CUENTA_SIN_ACTIVAR, F0, AQ10, F1, F2, F3, F4, F5, SUGERENCIAS_DUA, BARRERAS_PERSISTENTES, PLAN_SIN_BORRADOR, PLAN_BORRADOR, PLAN_CONCERTACION, PLAN_NEGOCIACION, PLAN_COMITE, PLAN_VALIDACION, PLAN_FIRMAS, PLAN_APROBADO, REDISENO_PENDIENTE, CONCERTACION_PENDIENTE, F8_ABIERTO, PERCEPCION_PENDIENTE, F8_POR_ABRIR, F9_PENDIENTE, F9_BORRADOR, F10_PENDIENTE, F10_APROBACION`. `prioridad` `ALTA|MEDIA|BAJA`. Los campos `plan_id/ajuste_id/corte/fecha_limite` solo aparecen cuando aplican.

**Contrato de `ruta_frontend`** (el frontend define las pantallas; estas son las rutas que el backend devuelve):
Estudiante: `/estudiante/{consentimiento|aq10|perfil|mi-ruta|barreras|plan|seguimiento|evaluacion|continuidad}`.
Bienestar: `/bienestar/estudiantes/{id}` y `/bienestar/estudiantes/{id}/{consentimiento|aq10|f1|f2|f3|f4|f5|sugerencias|plan|matriz|seguimiento|f9|f10|inasistencia}`.
Coordinador: `/coordinador/estudiantes/{id}`, `/coordinador/planes/{plan_id}`. Docente: `/docente/ajustes/{ajuste_id}`.

**`PUT /estudiantes/{id}/bienestar`** `{bienestar_usuario_id: int|null}` → `{"estudiante_id": 8, "bienestar_asignado": {"id": 3, "nombre_completo": "…"}|null}`. `422 BIENESTAR_INVALIDO` si no es un profesional de Bienestar activo. Se audita (`ASIGNACION_BIENESTAR`).

## 5. Inasistencia (RF-31, D15)

`POST /estudiantes/{id}/inasistencia` (201) `{porcentaje_inasistencia: 0-100, semestre_academico?, asignatura_id?, fecha_registro?, observaciones?}` (`semestre_academico` por defecto: el del calendario activo; `422 SEMESTRE_REQUERIDO` si no hay).
```json
{ "registro": {"id": 1, "estudiante_id": 8, "asignatura_id": null, "semestre_academico": "2026-II", "fecha_registro": "2026-11-16",
               "porcentaje_inasistencia": 25.0, "fuente": "MANUAL", "alerta_generada": true, "observaciones": null, "registrado_por_id": 3},
  "umbral": 20.0, "supera_umbral": true, "alerta_enviada": true, "alerta_ya_enviada_en_el_periodo": false }
```
Umbral = parámetro `umbral_inasistencia` (PARAMETRO_SISTEMA, por defecto 20; **no** se usa `calendario.umbral_inasistencia`). Si `porcentaje >= umbral`: correo inmediato (`INASISTENCIA_UMBRAL`) al profesional de Bienestar del estudiante y a los Coordinadores del programa, **una vez por estudiante y semestre** (los registros posteriores del mismo semestre solo guardan el dato).
`GET /estudiantes/{id}/inasistencia` → `{"umbral": 20.0, "items": [registro…]}` (más reciente primero).
`POST /estudiantes/{id}/inasistencia/sigaa` (cuerpo opcional `{semestre_academico?}`): lee `GET {SIGAA_API_URL}/inasistencia?codigo=&semestre=` (respuesta `{"porcentaje_inasistencia": 12.5}`; token opcional `SIGAA_API_TOKEN`) y registra con `fuente: "SIGAA"`. **Desactivado por defecto**: `501 SIGAA_NO_CONFIGURADO`; si el servicio no responde: `502 SIGAA_NO_DISPONIBLE` (registrar manualmente).

## 6. Funciones para `run_daily_jobs` (slice A) — `app/services/seguimiento.py`

```python
cortes_proximos(db, hoy: date, dias: tuple[int, ...] = (7, 1)) -> list[dict]
# [{"corte": "C1", "fecha_corte": date, "dias_restantes": 7, "semestre": "2026-II", "calendario_id": 1, "programa_id": None}]
pendientes_de_corte(db, corte: str, *, calendario_id: int | None = None) -> list[dict]
# [{"plan_id","estudiante_id","estudiante_usuario_id","bienestar_usuario_id","docente_usuario_ids":[…],"ajuste_ids":[…],
#   "estado_corte": "SIN_ABRIR"|"ABIERTO","calendario_id","fecha_corte": date,"semestre"}]   # planes IMPLEMENTACION/SEGUIMIENTO con el F8 del corte sin cerrar
tasa_implementacion(db, plan_id, hasta="C2") -> dict    # D6;  porcentaje_verde(db, plan_id) -> dict   # D8
```
Uso sugerido: `for c in cortes_proximos(db, hoy): for p in pendientes_de_corte(db, c["corte"], calendario_id=c["calendario_id"]): notify(Evento.RECORDATORIO_CORTE_7D / _1D, [bienestar, estudiante, *docentes], …, dedupe_key=f"corte:{corte}:{semestre}:{dias}d")`.
Otros helpers estables: `services.semaforo.{coordinadores_del_programa, docentes_responsables, bienestar_responsable, estado_seguimiento, construir_matriz, rojos_sin_rediseno}`.

## 7. Cambios de esquema (migración `00C2`)

* `registro_seguimiento_ajuste.semaforo` pasa a **NULLABLE** (la percepción del estudiante puede crear la fila antes de que Bienestar valore); + `tarea_concertacion` JSON, `rediseno` JSON.
* `seguimiento.barreras_emergentes` JSON.
* `evaluacion_plan`: + `estado` (`BORRADOR` por defecto), `cerrada_at`, `sintesis` JSON, `valoracion_dimensiones` JSON.
* `decision_plan.lecciones_aprendidas` TEXT.

## 8. Auditoría (`LOG_AUDITORIA`)
`CAMBIO_SEMAFORO`, `SEGUIMIENTO_ABIERTO|ACTUALIZADO|CERRADO`, `PERCEPCION_REGISTRADA`, `CONCERTACION_RESUELTA`, `REDISENO_REGISTRADO`, `REGISTRO_SEGUIMIENTO_CREADO`, `EVIDENCIA_EFECTIVIDAD_CREADA`, `BARRERA_EMERGENTE_REGISTRADA`, `EVALUACION_CREADA|ACTUALIZADA|CERRADA`, `INASISTENCIA_REGISTRADA`, `ASIGNACION_BIENESTAR`, `ELIMINACION_LOGICA`, más `NOTIFICACION_ENVIADA` (de `notify`).

## 9. Matriz de acceso resumida (§12.1)

| Recurso | Admin | Bienestar | Coordinador | Docente | Estudiante | Familiar |
|---|---|---|---|---|---|---|
| Seguimiento F8 (lectura) | — | ✔ | ✔ (su programa) | ✔ solo sus ajustes, vista reducida | ✔ propio | ✔ si autorizó `SEGUIMIENTO` |
| Seguimiento F8 (escritura) | — | ✔ | — | — | solo percepción propia | — |
| Evaluación F9 | — | ✔ lectura/escritura | lectura | — | lectura | — |
| Tablero `/estudiantes` | todos (datos básicos) | ✔ | su programa | — | — | — |
