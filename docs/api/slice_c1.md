# Slice C1 — Plan MAAR-TEA (F6), concertación, negociación, firmas, F7 y exportación

Prefijo `/api/v1`. JSON `snake_case`. Auth: `Authorization: Bearer <jwt>` (ver `auth.md`). Errores: `{"detail": "<español>", "code": "SNAKE_CASE"}`
(los 422 de validación agregan `errores: [{campo, mensaje}]`; algunos 409/422 agregan campos extra, indicados abajo).
Todo lo de un estudiante exige F0 firmado (`403 CONSENTIMIENTO_REQUERIDO` para el estudiante, `403 ESTUDIANTE_SIN_CONSENTIMIENTO` para el resto).
Soft delete: nada se borra físicamente; `DELETE` = soft delete con `motivo`.

## 1. Conceptos

**Estados del plan** (`estado`): `BORRADOR → EN_CONCERTACION → PENDIENTE_VALIDACION → PENDIENTE_FIRMAS → APROBADO → IMPLEMENTACION → SEGUIMIENTO → FINALIZADO → ARCHIVADO`,
más `EN_NEGOCIACION` y `ESCALADO_COMITE`. Transiciones inválidas → `409 TRANSICION_PLAN_INVALIDA`. Solo hay **un plan activo (no `ARCHIVADO`) por estudiante y semestre**.

```
BORRADOR ──enviar-a-estudiante──▶ EN_CONCERTACION ──(objeción)──▶ EN_NEGOCIACION ──(3 ciclos sin acuerdo)──▶ ESCALADO_COMITE
                                   │  ▲                               │ (acuerdo / cierre)                      │ (cerrar)
                                   │  └───────────────────────────────┴─────────────────────────────────────────┘
                                   └─enviar-a-validacion──▶ PENDIENTE_VALIDACION ──validar──▶ PENDIENTE_FIRMAS ──3 firmas──▶ APROBADO ──iniciar-implementacion──▶ IMPLEMENTACION
        (devolver: PENDIENTE_VALIDACION / PENDIENTE_FIRMAS ──▶ EN_CONCERTACION)    (editar un plan ya validado/aprobado reabre EN_CONCERTACION con versión nueva)
```

**Versiones.** `version` es el número vigente. Se **congela** (snapshot + hash SHA-256) cuando el Coordinador valida (`PENDIENTE_FIRMAS`). Editar un plan en
`PENDIENTE_FIRMAS` con firmas, o en `APROBADO/IMPLEMENTACION/SEGUIMIENTO`, abre la versión N+1 (estado `EN_CONCERTACION`), marca `INVALIDADA` las firmas de la
versión N y conserva su snapshot (marcado `reemplazada`). Las respuestas de los endpoints de edición traen `plan: {id, estado, version, nueva_version}`.
Editar en `PENDIENTE_VALIDACION` reabre la concertación sin versión nueva. `FINALIZADO/ARCHIVADO`: `409 PLAN_NO_EDITABLE`.

**Categorías de ajuste** (`tipo_ajuste`) y valores de `detalle.tipo`:

| `tipo_ajuste` | `detalle.tipo` (enum) |
|---|---|
| `COMUNICACION` | `INSTRUCCIONES_ESCRITAS, INSTRUCCIONES_VERBALES, ANTICIPO_INFORMACION, COMUNICACION_CLARA, CONFIRMACION, RESUMEN_ESCRITO` |
| `PEDAGOGIA` | `MATERIALES_ANTICIPADOS, METODOLOGIA_ALTERNATIVA, ESTRUCTURA_ADICIONAL, TIEMPO_PROCESAMIENTO, APRENDIZAJE_PARES, TUTORIAS` |
| `EVALUACION` | `TIEMPO_EXTENDIDO, INSTRUCCIONES_CLARAS, FORMATO_ALTERNATIVO, AMBIENTE_APOYO, DESCANSOS, RETROALIMENTACION_ADICIONAL` |
| `AMBIENTE` | `ESPACIO_TRANQUILO, REDUCCION_ESTIMULOS, ILUMINACION_MODIFICADA, RUIDO_CONTROLADO, UBICACION_ESPECIFICA, ELEMENTOS_SENSORIALES` |
| `INTERACCION` | `TRABAJO_INDIVIDUAL, TRABAJO_PARES, ESTRUCTURA_GRUPO, ROL_DEFINIDO, MEDIACION_DOCENTE, TUTORIA_PARES` |
| `TECNOLOGIA` | `SOFTWARE_ACCESIBILIDAD, PLATAFORMA_ALTERNATIVA, HERRAMIENTA_ASISTIVA, HARDWARE_ESPECIAL, ACCESO_ANTICIPADO, SINCRONIZACION_ASINCRONICO` (+ `soporte_tecnico_requerido: bool`) |

`detalle = {tipo, descripcion, soporte_tecnico_requerido?}` (en la respuesta, `soporte_tecnico_requerido` solo aparece en `TECNOLOGIA`).
Tipo que no corresponde a la categoría → `422 DETALLE_AJUSTE_INVALIDO` (con `tipos_validos: [...]`).

**Otros enums.** `especificidad`: `GENERAL | PARA_ASIGNATURA | PARA_ACTIVIDAD` (se infiere si no se envía). Estado del ajuste `estado`: `PROPUESTO | ACORDADO | IMPLEMENTACION | ACTIVO | EVALUACION | MODIFICADO | RETIRADO`.
`dimension_dua`: `MULTIPLES_MEDIOS_PRESENTACION | MULTIPLES_MEDIOS_ACCION | MULTIPLES_MEDIOS_PARTICIPACION`. `escenario`: `AULA, CAMPUS, VIRTUALIDAD, LABORATORIOS, PRACTICA_CLINICA, PRACTICA_SALUD_PUBLICA, EVENTOS, PASANTIAS`.
`respuesta_estudiante.respuesta`: `ACEPTADO | MODIFICACION_PROPUESTA | OBJETADO`. `rol_firmante`: `ESTUDIANTE | BIENESTAR | COORDINADOR`. Estado de firma: `FIRMADA | INVALIDADA`.
Semáforo `valor`: `VERDE | AMARILLO | ROJO` (solo lectura: último `REGISTRO_SEGUIMIENTO_AJUSTE`, lo escribe el slice de seguimiento; siempre con `texto`).
Negociación `estado`: `ABIERTA` (espera contrapropuesta de Bienestar) · `EN_CICLO` (espera respuesta del estudiante) · `ACORDADA` · `ESCALADA_COMITE` · `CERRADA`.
Exportación `estado`: `SOLICITADA | PROCESANDO | LISTA | ERROR | EXPIRADA`.

**Matriz de acceso (§12.1).** Bienestar: CRUD. Coordinador: lectura + validar/devolver + firmar + editar F7 (solo su programa). Estudiante: su plan (no ve `BORRADOR`), concertar y firmar.
Docente: solo planes **vigentes** (APROBADO, IMPLEMENTACION, SEGUIMIENTO, FINALIZADO) donde tiene ajustes (su asignatura o es responsable), solo esos ajustes, **sin datos clínicos**. Familiar: lectura si el estudiante autorizó el alcance `PLAN`. Admin: sin acceso al plan.
Fuera de alcance → `403 ACCESO_DENEGADO`.

## 2. Objetos

### Plan (`GET /planes/{id}`, vista `COMPLETA`)
```json
{
  "id": 12, "vista": "COMPLETA",
  "estudiante": {"id": 5, "nombre_completo": "Ana Pérez", "codigo_estudiante": "E00005", "programa_id": 1, "programa": "Enfermería"},
  "semestre_academico": "2026-II", "estado": "EN_CONCERTACION", "version": 1,
  "fecha_elaboracion": "2026-11-16", "vigencia_inicio": "2026-08-03", "vigencia_fin": "2026-12-12", "fecha_aprobacion": null,
  "ciclos_negociacion": 0, "semaforo_actual": null,
  "elaborado_por": {"id": 3, "nombre_completo": "Bienestar 1", "rol": "BIENESTAR"},
  "validado_por": null, "fecha_validacion": null, "comentarios_validacion": null, "enviado_a_estudiante_at": "2026-11-16T15:00:00+00:00",
  "resumen_ejecutivo": null, "justificacion_apoyos": null, "participacion_estudiante": true, "participacion_familia": false,
  "ajustes": [ /* Ajuste */ ], "estrategias_dua": [ /* EstrategiaDua */ ],
  "resumen": {"total_ajustes": 3, "total_estrategias_dua": 1, "por_categoria": {"AMBIENTE": 1}, "por_semaforo": {"AMARILLO": 1},
              "aceptados_por_estudiante": 1, "pendientes_estudiante": 2, "objetados": 0, "pendientes_docente": 0},
  "firmas": [ /* Firma, todas las versiones */ ],
  "firmas_estado": {"version": 1, "orden": ["ESTUDIANTE","BIENESTAR","COORDINADOR"], "firmadas": [], "pendientes": ["ESTUDIANTE","BIENESTAR","COORDINADOR"], "completas": false},
  "hash_contenido": "<sha256 del contenido vigente>",
  "puede_enviar_a_validacion": false, "razones_no_listo": ["El estudiante aún no ha aceptado el ajuste «…»."],
  "negociaciones_abiertas": [ /* Negociacion */ ],
  "participacion": [{"fecha": "…", "usuario_id": 3, "rol": "BIENESTAR", "accion": "PROPUSO", "entidad": "ajuste", "entidad_id": 7, "detalle": null}],
  "acciones_disponibles": ["EDITAR", "ENVIAR_A_VALIDACION"], "matriz_generada": false
}
```
* `acciones_disponibles` (según rol y estado; el frontend solo habilita botones con esto): `EDITAR, ENVIAR_A_ESTUDIANTE, ELIMINAR, ENVIAR_A_VALIDACION, GENERAR_MATRIZ, INICIAR_IMPLEMENTACION, ARCHIVAR, FIRMAR, VALIDAR, DEVOLVER, EDITAR_MATRIZ, RESPONDER_AJUSTES, ACEPTAR_RESPONSABILIDAD, EXPORTAR`.
* `participacion[].accion`: `CREO_BORRADOR, PROPUSO, MODIFICO, ELIMINO, ENVIO_A_ESTUDIANTE, ACEPTO, PROPUSO_MODIFICACION, OBJETO, CONTRAPROPUSO, ESCALO_A_COMITE, CERRO_NEGOCIACION, ENVIO_A_VALIDACION, VALIDO, DEVOLVIO, FIRMO, NUEVA_VERSION, ACEPTO_RESPONSABILIDAD, DECLINO_RESPONSABILIDAD, INICIO_IMPLEMENTACION, ARCHIVO` (`rol: "SISTEMA"` = borrador asistido).
* **Vista `DOCENTE`**: `{id, vista:"DOCENTE", estudiante, semestre_academico, estado, version, fechas, elaborado_por, ajustes (solo los suyos), estrategias_dua (solo las suyas), resumen, acciones_disponibles, matriz_generada}`; en sus ajustes `barrera` solo trae `{id, tipo_barrera, escenario}` y **no** hay `justificacion`, `fortaleza`, `respuesta_estudiante`, `negociacion`, `origen`, `propuesto_por`. No trae `resumen_ejecutivo`, `firmas`, `participacion`, `hash_contenido`.
* **Familiar**: vista completa con `participacion: []` y `negociaciones_abiertas: []`.

### Ajuste
```json
{
  "id": 7, "plan_id": 12, "nombre_ajuste": "Ambiente de menor estimulación", "descripcion_ajuste": "…", "justificacion": "Responde a la barrera sensorial … Se apoya en la fortaleza «…».",
  "tipo_ajuste": "AMBIENTE", "categoria": "Ambiente", "detalle": {"tipo": "RUIDO_CONTROLADO", "descripcion": "…"},
  "barrera": {"id": 4, "tipo_barrera": "SENSORIAL", "escenario": null, "descripcion_barrera": "…", "severidad": "MODERADA"},
  "fortaleza": {"id": 2, "nombre_fortaleza": "Atención al detalle"},
  "responsable": {"id": 9, "nombre_completo": "Docente 1", "rol": "DOCENTE"},
  "asignatura": {"id": 1, "codigo": "ENF101", "nombre": "Fundamentos de Enfermería"}, "asignatura_si_aplica": "Fundamentos de Enfermería", "actividad_si_aplica": null,
  "especificidad": "PARA_ASIGNATURA", "recurso": "Salón reservado", "frecuencia": "Cada sesión de clase", "indicador_efectividad": "…",
  "fecha_inicio": "2026-08-03", "fecha_fin_prevista": "2026-12-12", "permanencia_indefinida": false, "estado": "PROPUESTO",
  "origen": "BORRADOR_ASISTIDO", "propuesto_por": {"id": null, "rol": "SISTEMA", "nombre_completo": null},
  "modificado_por": null, "modificado_at": null,
  "aceptado_por_estudiante": null,
  "respuesta_estudiante": {"respuesta": null, "comentario": null, "modificacion_propuesta": null, "fecha": null},
  "aceptacion_docente": {"aceptado": null, "comentario": null, "fecha": null},
  "semaforo": {"valor": "AMARILLO", "corte": "C1", "texto": "Amarillo: funciona en parte, hay que concertar cambios", "fecha": "…"},
  "negociacion": {"id": 3, "estado": "ABIERTA", "ciclo": 1, "max_ciclos": 3, "siguiente_accion": "BIENESTAR_CONTRAPROPONE"}
}
```
`aceptado_por_estudiante`: `true` aceptó · `false` objetó · `null` pendiente / propuso modificación. `semaforo` y `negociacion` pueden ser `null`.

### EstrategiaDua
`{id, plan_id, nombre_estrategia, descripcion, dimension_dua, alcance, escenario, responsable: Ref|null, asignatura|null, fecha_inicio_implementacion, estado_implementacion, implementada, estrategia_catalogo_id, sugerencia_id, barrera: {id,tipo_barrera,escenario,descripcion_barrera?,severidad?}|null, fortaleza?, origen?: "SUGERENCIA_DUA"|"MANUAL", propuesta_por?, modificado_por?}`.

### Firma
`{id, version, rol_firmante, firmante: {id, nombre_completo, rol}, firmado_at, estado, hash_documento, hash_corto, firma_hash, ip}`.

### Negociacion
```json
{"id": 3, "plan_id": 12, "estudiante_id": 5, "ajuste": {"id": 7, "nombre_ajuste": "…", "tipo_ajuste": "AMBIENTE"},
 "tipo": "OBJECION_AJUSTE", "estado": "EN_CICLO", "ciclo": 2, "max_ciclos": 3,
 "objecion_estudiante": "…", "propuesta_bienestar": "…", "resolucion": null,
 "historial": [{"ciclo": 1, "objecion": "…", "propuesta": "…", "resolucion": "SIN_ACUERDO", "respuesta_estudiante": "…", "fecha": "…"}],
 "siguiente_accion": "ESTUDIANTE_RESPONDE", "creada_por": Ref, "asignada_a": Ref, "escalada_at": null, "resuelta_at": null, "created_at": "…"}
```
`siguiente_accion`: `BIENESTAR_CONTRAPROPONE | ESTUDIANTE_RESPONDE | COMITE_DECIDE | null`. `historial[].resolucion`: `SIN_ACUERDO | ACORDADO | <resultado de cierre> | null`. `Ref = {id, nombre_completo, rol}`.

### Listados paginados
`?page=1&page_size=20` → `{items, total, page, page_size}`. Item de plan: `{id, estudiante_id, estudiante_nombre, programa_id, semestre_academico, estado, version, total_ajustes, semaforo_actual, fecha_elaboracion, fecha_aprobacion, updated_at}`.

## 3. Endpoints de plan

| Método y ruta | Roles | Cuerpo | Respuesta | Errores (`code`) |
|---|---|---|---|---|
| `POST /estudiantes/{eid}/planes` | BIENESTAR | `{semestre_academico?, resumen_ejecutivo?, justificacion_apoyos?, incluir_sugerencias?: true}` (cuerpo opcional) | `201 {plan: Plan, avisos: [str]}` | `409 PLAN_ACTIVO_EXISTENTE` (+`plan_id`, `estado`), `409 SEMESTRE_ACTIVO_NO_DEFINIDO`, `404 ESTUDIANTE_NO_ENCONTRADO`, `403 ACCESO_DENEGADO`, `403 ESTUDIANTE_SIN_CONSENTIMIENTO` |
| `GET /estudiantes/{eid}/planes` | BIENESTAR, COORDINADOR, ESTUDIANTE (el suyo), DOCENTE, FAMILIAR | — | paginado de items | `403 ACCESO_DENEGADO` |
| `GET /planes` | BIENESTAR, COORDINADOR, ESTUDIANTE, DOCENTE, FAMILIAR | query: `estado`, `semestre_academico`, `estudiante_id`, `programa_id`, `q` (nombre/código), `page`, `page_size` | paginado de items (alcance por rol; estudiante/familiar no ven `BORRADOR`) | `403 ROL_NO_PERMITIDO` (p. ej. ADMIN) |
| `GET /planes/mio` | ESTUDIANTE | — | `Plan` más reciente que no sea `BORRADOR`/`ARCHIVADO` | `404 SIN_PLAN` |
| `GET /planes/{id}` | BIENESTAR, COORDINADOR, ESTUDIANTE, DOCENTE (vista DOCENTE), FAMILIAR | — | `Plan` | `404 PLAN_NO_ENCONTRADO`, `403 ACCESO_DENEGADO` |
| `PATCH /planes/{id}` | BIENESTAR | `{resumen_ejecutivo?, justificacion_apoyos?, vigencia_fin?, participacion_familia?, profesionales_responsables_ids?}` | `{plan: Plan, cambio: {id, estado, version, nueva_version}}` | `422 FECHAS_INVALIDAS`, `409 PLAN_NO_EDITABLE` |
| `DELETE /planes/{id}?motivo=` | BIENESTAR | — | `204` (soft delete; solo `BORRADOR`) | `409 PLAN_NO_ELIMINABLE` |
| `POST /planes/{id}/archivar` | BIENESTAR | `{motivo}` | `{id, estado, version, nueva_version:false}` | `409 TRANSICION_PLAN_INVALIDA` |
| `POST /planes/{id}/sugerencias/incorporar` | BIENESTAR | — | `{incorporadas: n, plan: {…}}` (agrega sugerencias DUA aceptadas después del borrador) | — |

**Borrador asistido (RF-21).** Combina barreras **persistentes** (F4; si ninguna está marcada `PERSISTENTE` usa las vigentes no superadas y lo dice en `avisos`), facilitadores (F5), fortalezas (F2) y sugerencias DUA `ACEPTADA/MODIFICADA`.
Crea un ajuste candidato por barrera (`origen: BORRADOR_ASISTIDO`, `propuesto_por.rol: "SISTEMA"`) con `barrera` y `fortaleza` enlazadas, y una `EstrategiaDua` por sugerencia aceptada. El semestre es el del calendario activo.

### Estrategias DUA del plan (Bienestar)
| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /planes/{id}/estrategias-dua` | `{estrategia_catalogo_id? , nombre_estrategia?, descripcion?, dimension_dua?, barrera_id?, fortaleza_id?, responsable_implementacion_id?, asignatura_id?, escenario?, alcance?, fecha_inicio_implementacion?}` (con catálogo se completan nombre/descripción/dimensión; sin catálogo son obligatorios) | `201 {estrategia, plan:{id,estado,version,nueva_version}}` |
| `PATCH /planes/{id}/estrategias-dua/{sid}` | mismos campos (sin `estrategia_catalogo_id`) | `{estrategia, plan}` |
| `DELETE /planes/{id}/estrategias-dua/{sid}?motivo=` | — | `{plan}` |

Errores: `422 ESTRATEGIA_INCOMPLETA`, `422 CATALOGO_DUA_INVALIDO`, `422 BARRERA_INVALIDA`, `422 FORTALEZA_INVALIDA`, `422 RESPONSABLE_INVALIDO`, `422 ASIGNATURA_INVALIDA`, `404 ESTRATEGIA_NO_ENCONTRADA`.

### Ajustes razonables (Bienestar escribe; lectura por rol)
**`POST /planes/{id}/ajustes`** → `201 {ajuste, plan}`
```json
{"tipo_ajuste": "AMBIENTE", "detalle": {"tipo": "ESPACIO_TRANQUILO", "descripcion": "Sala aparte"},
 "nombre_ajuste": "Sala tranquila para exámenes", "descripcion_ajuste": "Presentar el examen en un salón silencioso",
 "justificacion": null, "barrera_asociada_id": 4, "fortaleza_apoyo_id": 2, "responsable_id": 9, "asignatura_id": 1,
 "asignatura_si_aplica": null, "actividad_si_aplica": null, "especificidad": null, "recurso": "Salón reservado",
 "frecuencia": "Cada examen", "indicador_efectividad": "…", "fecha_inicio": null, "fecha_fin_prevista": null, "permanencia_indefinida": null}
```
Obligatorios: `tipo_ajuste`, `detalle`, `nombre_ajuste`, `descripcion_ajuste`, `barrera_asociada_id` (la barrera que resuelve; debe ser del estudiante). `fecha_inicio` por defecto = inicio de vigencia.
`PATCH /planes/{id}/ajustes/{aid}` (mismos campos, todos opcionales) → `{ajuste, plan}`: un cambio real **reinicia la revisión** del ajuste (`respuesta_estudiante` y `aceptacion_docente` vuelven a `null`, `estado: PROPUESTO`) y registra `modificado_por`. Sin cambios no hace nada.
`GET /planes/{id}/ajustes/{aid}` → `{ajuste, plan}` (todos los roles de lectura; el docente solo los suyos). `DELETE /planes/{id}/ajustes/{aid}?motivo=` → `{plan}` (cierra su negociación abierta, si la hay).
Errores: `422 BARRERA_REQUERIDA`, `422 BARRERA_INVALIDA`, `422 FORTALEZA_INVALIDA`, `422 RESPONSABLE_INVALIDO`, `422 ASIGNATURA_INVALIDA`, `422 FECHAS_INVALIDAS`, `422 DETALLE_AJUSTE_INVALIDO`, `409 AJUSTE_EN_NEGOCIACION` (editar un ajuste con negociación abierta: use la contrapropuesta), `409 PLAN_NO_EDITABLE`, `404 AJUSTE_NO_ENCONTRADO`, `403 AJUSTE_NO_ES_SUYO`.

## 4. Workflow de concertación

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `POST /planes/{id}/enviar-a-estudiante` | BIENESTAR | — | `{id, estado:"EN_CONCERTACION", version, nueva_version}` | `409 PLAN_VACIO` (sin ajustes ni estrategias), `409 TRANSICION_PLAN_INVALIDA` |
| `POST /planes/{id}/ajustes/{aid}/respuesta-estudiante` | ESTUDIANTE | `{respuesta: "ACEPTADO"\|"MODIFICACION_PROPUESTA"\|"OBJETADO", comentario?}` (comentario ≥ 5 caracteres obligatorio en los dos últimos) | `{ajuste_id, respuesta, negociacion: {id, estado, ciclo}\|null, plan, ajuste}` (`OBJETADO` abre la negociación ciclo 1 y el plan pasa a `EN_NEGOCIACION`) | `422 COMENTARIO_REQUERIDO`, `409 PLAN_NO_ESTA_EN_CONCERTACION`, `409 AJUSTE_EN_NEGOCIACION` |
| `POST /planes/{id}/enviar-a-validacion` | BIENESTAR | — | `{id, estado:"PENDIENTE_VALIDACION", …}` y aviso al Coordinador | `409 PLAN_NO_LISTO_PARA_VALIDACION` (+`razones: [str]`), `409 TRANSICION_PLAN_INVALIDA` |
| `POST /planes/{id}/validar` | COORDINADOR | `{comentario?}` | `{id, estado:"PENDIENTE_FIRMAS", version, nueva_version, hash_version}` (congela la versión) y aviso «Plan listo para firma» | `409 TRANSICION_PLAN_INVALIDA` |
| `POST /planes/{id}/devolver` | COORDINADOR | `{comentarios}` (≥ 5) | `{id, estado:"EN_CONCERTACION", …}`; el texto queda en `comentarios_validacion` | `409 TRANSICION_PLAN_INVALIDA` |
| `POST /planes/{id}/ajustes/{aid}/aceptacion-docente` | DOCENTE | `{acepta: bool, comentario?}` (comentario obligatorio si `acepta=false`) | `{ajuste, plan}` | `409 PLAN_NO_APROBADO`, `403 AJUSTE_NO_ES_SUYO`, `422 COMENTARIO_REQUERIDO` |
| `POST /planes/{id}/iniciar-implementacion` | BIENESTAR | — | `{id, estado:"IMPLEMENTACION", …}` | `409 MATRIZ_PENDIENTE`, `409 TRANSICION_PLAN_INVALIDA` |

Condición de `enviar-a-validacion`: todos los ajustes con `aceptado_por_estudiante=true` (o desacuerdo ya cerrado por decisión del Comité), ninguna `modificacion_propuesta` pendiente y ninguna negociación abierta.
Notificaciones (M10, eventos existentes): «Plan listo para firma» (al Coordinador al pedir validación; a estudiante, Bienestar y Coordinador al validar), «Plan firmado y aprobado» (todos los actores), «Desacuerdo escalado al Comité de Inclusión», «Su exportación está lista».

## 5. Negociación (RF-25, D12) — prefijo `/negociacion`

Ciclo: estudiante objeta (ciclo 1, `ABIERTA`) → Bienestar contrapropone (`EN_CICLO`) → estudiante acepta (`ACORDADA`) o rechaza con nueva objeción (ciclo + 1, `ABIERTA`); si rechaza en el último ciclo → `ESCALADA_COMITE`
(plan `ESCALADO_COMITE`; aviso al Comité de Inclusión —parámetro `comite_inclusion_emails`, lista de correos— y a todos los actores del plan). **Máximo `max_ciclos_negociacion`** (parámetro, por defecto 3, tope 3).

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `GET /negociacion` | BIENESTAR, COORDINADOR, ESTUDIANTE (alcance por rol) | query: `plan_id`, `estado`, `estudiante_id`, `page`, `page_size` | paginado de `Negociacion` | — |
| `GET /negociacion/{id}` | idem | — | `Negociacion` | `404 NEGOCIACION_NO_ENCONTRADA` |
| `POST /negociacion/{id}/contrapropuesta` | BIENESTAR | `{propuesta (≥5), cambios_ajuste?: {…campos de PATCH ajuste…}}` | `Negociacion` (`EN_CICLO`) | `409 NEGOCIACION_ESTADO_INVALIDO` |
| `POST /negociacion/{id}/responder` | ESTUDIANTE | `{acepta: bool, comentario?}` (si `acepta=false`, `comentario` ≥ 5 = nueva objeción) | `Negociacion` (`ACORDADA`, ciclo siguiente `ABIERTA` o `ESCALADA_COMITE`) | `422 COMENTARIO_REQUERIDO`, `409 NEGOCIACION_ESTADO_INVALIDO` |
| `POST /negociacion/{id}/cerrar` | BIENESTAR; COORDINADOR solo si `ESCALADA_COMITE` | `{resultado: "ACORDADO"\|"RETIRAR_AJUSTE"\|"MANTENER_POR_COMITE", resolucion (≥5)}` | `Negociacion` | `409 NEGOCIACION_NO_ESCALADA` (`MANTENER_POR_COMITE` solo en escaladas), `409 NEGOCIACION_ESTADO_INVALIDO`, `403 ROL_NO_PERMITIDO` |

Al cerrar sin negociaciones abiertas, el plan vuelve a `EN_CONCERTACION`. `RETIRAR_AJUSTE` retira (soft delete) el ajuste.

## 6. Firma digital (RF-24)

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `POST /planes/{id}/firmar` | ESTUDIANTE, BIENESTAR, COORDINADOR (cada uno solo su firma) | `{confirmo: true}` | `201 {firma: Firma, aprobado: bool, matriz: {generada, apoyos?, motivo?, code?}\|null, firmas_estado, plan}` | `422 CONFIRMACION_REQUERIDA`, `409 PLAN_NO_ESTA_EN_FIRMAS`, `409 FIRMA_YA_REGISTRADA`, `409 FIRMA_FUERA_DE_ORDEN`, `409 PLAN_MODIFICADO`, `403 ROL_NO_PERMITIDO` |
| `GET /planes/{id}/firmas` | BIENESTAR, COORDINADOR, ESTUDIANTE, FAMILIAR | — | `{plan_id, version, estado_firmas, firmas: [Firma]}` (todas las versiones) | `403 ROL_NO_PERMITIDO` (docente) |
| `GET /planes/{id}/verificar` | idem | — | ver abajo (auditado) | — |

* Cada firma guarda sello de tiempo del servidor, **hash SHA-256 del contenido canónico** de la versión, IP y user-agent. Con las tres firmas vigentes el plan pasa a `APROBADO` y se genera la F7 automáticamente (si no hay calendario activo el plan queda aprobado y `matriz.generada=false`, `matriz.code="CALENDARIO_NO_CONFIGURADO"`).
* Orden: parámetros `plan_firmas_orden` (por defecto `["ESTUDIANTE","BIENESTAR","COORDINADOR"]`, solo informativo) y `plan_firmas_orden_estricto` (bool, por defecto `false`: con `true` exige el orden).
* Cualquier modificación posterior invalida las firmas de esa versión (`estado: INVALIDADA`); las firmas no se borran.

`GET /planes/{id}/verificar` →
```json
{"plan_id": 12, "version": 2, "integro": true, "firmas_vigentes": 3, "firmas_validas": 3, "completo": true,
 "versiones": [{"version": 2, "hash_actual": "…", "origen_hash": "contenido_actual", "hash_snapshot": "…",
                "firmas": [{"id": 9, "rol_firmante": "ESTUDIANTE", "firmante_id": 5, "firmado_at": "…", "estado": "FIRMADA",
                            "hash_documento": "…", "hash_coincide": true, "sello_firma_valido": true, "valida": true}]}]}
```
`origen_hash`: `contenido_actual` (versión vigente, recalculada desde la BD) | `snapshot_congelado` (versiones previas) | `sin_snapshot`. `integro=false` si alguna firma vigente no coincide.

## 7. Versiones (HU-20)

| Método y ruta | Roles | Respuesta |
|---|---|---|
| `GET /planes/{id}/versiones` | BIENESTAR, COORDINADOR, ESTUDIANTE, FAMILIAR | `{plan_id, version_actual, items: [Version sin snapshot]}` (más reciente primero) |
| `GET /planes/{id}/versiones/{n}` | idem | `Version` con `snapshot` (`404 VERSION_NO_ENCONTRADA`) |

`Version = {version, vigente, congelada, reemplazada, motivo_reemplazo, estado_plan, hash_snapshot, motivo_cambio, creado_por, created_at, firmas: [Firma], snapshot?}`.
La versión vigente aún sin validar aparece con `congelada:false` (snapshot en vivo). `snapshot = {plan, estrategias_dua[], ajustes[]}` (contenido canónico).

## 8. F7 — Matriz de responsabilidades (RF-26, HU-14)

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `POST /planes/{id}/matriz` | BIENESTAR, COORDINADOR (su programa) | `{sobrescribir?: false}` (cuerpo opcional) | `201 Matriz` | `409 CALENDARIO_NO_CONFIGURADO`, `409 PLAN_NO_APROBADO` |
| `GET /planes/{id}/matriz` | BIENESTAR, COORDINADOR, ESTUDIANTE, FAMILIAR, DOCENTE (solo sus apoyos) | — | `Matriz` | — |
| `PATCH /planes/{id}/matriz/apoyos/{apoyo_id}` | BIENESTAR, COORDINADOR | `{fecha_inicio?, fecha_fin_prevista?, intensidad?, estado?, objetivo?, continuidad_indefinida?, frecuencia?, responsable_principal_id?, responsable_secundario_id?, recurso?: {tipo_recurso?, descripcion_recurso?, cantidad?, unidad_medida?, disponibilidad?}}` | `Matriz` | `422 FECHAS_FUERA_DE_CALENDARIO`, `422 FECHAS_INVALIDAS`, `404 APOYO_NO_ENCONTRADO`, `400 SIN_CAMBIOS` |
| `GET /planes/{id}/implementacion?corte=C1\|C2\|C3` | BIENESTAR, COORDINADOR | — | tasa de implementación | — |

Generación: un `APOYO` por ajuste y por estrategia DUA con `TIPO_APOYO`, `RESPONSABLE_APOYO` principal (el del ajuste, o Bienestar) y secundario, `RECURSO`, frecuencia y **fechas dentro del calendario activo** (cortes C1–C3). Regenerar es idempotente: conserva lo editado a mano salvo `sobrescribir=true`; retira apoyos de elementos que salieron del plan.
```json
{"plan_id": 12, "version": 2, "semestre_academico": "2026-II",
 "calendario": {"id": 1, "semestre_academico": "2026-II", "fecha_inicio": "2026-08-03", "fecha_fin": "2026-12-12",
                "cortes": [{"corte": "C1", "fecha": "2026-09-18"}, {"corte": "C2", "fecha": "2026-10-23"}, {"corte": "C3", "fecha": "2026-12-04"}]},
 "apoyos": [{"id": 31, "ajuste_id": 7, "estrategia_id": null, "nombre_apoyo": "…", "descripcion_apoyo": "…", "tipo_apoyo": "Ajuste razonable · Ambiente",
             "categoria_apoyo": "ACOMPANAMIENTO_BIENESTAR", "objetivo": "…", "fecha_inicio": "2026-08-03", "fecha_fin_prevista": "2026-12-12",
             "intensidad": "MEDIA", "estado": "PLANEADO", "frecuencia": "Cada sesión de clase",
             "responsable_principal": {"id": 40, "usuario": {"id": 9, "nombre_completo": "…", "rol": "DOCENTE"}, "cargo": "Docente", "frecuencia": "…", "porcentaje_dedicacion": 100, "fecha_asignacion": "2026-08-03"},
             "responsable_secundario": {"id": 41, "usuario": {…}, "cargo": "Profesional de Bienestar", …},
             "recurso": {"id": 50, "tipo_recurso": "ESPACIAL", "descripcion_recurso": "Salón reservado", "cantidad": null, "unidad_medida": null, "disponibilidad": "DISPONIBLE"},
             "cortes": [{"corte": "C2", "fecha": "2026-10-23"}], "implementaciones_ejecutadas": 1}],
 "tasa_implementacion": { /* ver abajo */ }}
```
`cortes` de cada apoyo = los del calendario que caen entre sus fechas.

**Tasa de implementación (D6, meta ≥ 80 % al C2)** = apoyos con ≥ 1 `IMPLEMENTACION_APOYO` en estado `EJECUTADA` (o estrategia DUA marcada `implementada`) / total de apoyos. Con `corte` cuenta solo hasta la fecha de ese corte.
`{plan_id, corte, hasta, total_apoyos, implementados, tasa (0–100 o null sin matriz), meta: 80.0, cumple_meta, detalle: [{apoyo_id, nombre_apoyo, implementaciones, implementado}]}`.
Para otros módulos (Python): `services.plan_builder.tasa_implementacion(db, plan_id, corte=None) -> float | None` y `resumen_implementacion(db, plan_id, corte=None) -> dict`.

## 9. Exportación (RF-27, RNF-03)

| Método y ruta | Roles | Respuesta | Errores |
|---|---|---|---|
| `POST /planes/{id}/exportar?formato=pdf\|docx\|html` (por defecto `pdf`) | BIENESTAR, COORDINADOR, ESTUDIANTE, FAMILIAR (con acceso al plan) | `202 Exportacion` | `422 DATOS_INVALIDOS` (formato), `403` |
| `GET /planes/{id}/exportaciones` | idem | paginado de `Exportacion` | — |
| `GET /exportaciones/{id}` | quien la pidió o quien puede leer el plan | `Exportacion` | `404 EXPORTACION_NO_ENCONTRADA` |
| `GET /exportaciones/{id}/descargar` | idem | archivo (`Content-Disposition: attachment`; con R2: `302` a URL prefirmada de 5 min). **Auditado** | `409 EXPORTACION_NO_LISTA`, `410 EXPORTACION_EXPIRADA` |

```json
{"id": 4, "plan_id": 12, "estado": "LISTA", "tipo": "PLAN_PDF", "formato": "html", "formato_solicitado": "pdf", "version_plan": 2,
 "aviso": "El servidor no puede generar PDF en este momento; se generó una versión HTML imprimible (imprímala o guárdela como PDF desde el navegador).",
 "archivo_nombre": "plan-maar-tea_E00005_v2_2026-11-16.html", "content_type": "text/html; charset=utf-8", "size_bytes": 20113, "error": null,
 "solicitada_por_id": 3, "created_at": "…", "completada_at": "…", "expira_at": "…", "descarga": "/api/v1/exportaciones/4/descargar"}
```
* La generación es asíncrona (Celery o en línea/hilo): consulte `GET /exportaciones/{id}` hasta `LISTA` (o `ERROR` con `error`). En el servidor sin broker puede estar `LISTA` ya en la respuesta del `POST`.
* **Degradación:** si WeasyPrint no está disponible (p. ej. Windows sin GTK) o falla, `formato: "html"` (HTML imprimible A4) y `aviso` lo explica; nunca un 500. `formato_solicitado` conserva lo que se pidió.
* El documento incluye datos del plan, estrategias DUA, ajustes por categoría (tablas con semáforo en texto), matriz F7 (si existe) y **firmas digitales visibles** (nombre, fecha/hora de Colombia, hash corto, estado) con el resultado de la verificación y la huella SHA-256. Un plan sin las tres firmas lleva el aviso «Borrador sin firmas completas».
* Vence a los 7 días (parámetro `dias_expiracion_exportacion`): el job diario `vencimiento_exportaciones` marca `EXPIRADA` y borra el archivo.

## 10. Códigos de error frecuentes (resumen)

`PLAN_NO_ENCONTRADO` 404 · `SIN_PLAN` 404 · `AJUSTE_NO_ENCONTRADO` 404 · `ESTRATEGIA_NO_ENCONTRADA` 404 · `VERSION_NO_ENCONTRADA` 404 · `NEGOCIACION_NO_ENCONTRADA` 404 · `APOYO_NO_ENCONTRADO` 404 · `EXPORTACION_NO_ENCONTRADA` 404 ·
`PLAN_ACTIVO_EXISTENTE` 409 · `SEMESTRE_ACTIVO_NO_DEFINIDO` 409 · `TRANSICION_PLAN_INVALIDA` 409 · `PLAN_NO_EDITABLE` 409 · `PLAN_NO_ELIMINABLE` 409 · `PLAN_VACIO` 409 · `PLAN_NO_LISTO_PARA_VALIDACION` 409 · `PLAN_NO_ESTA_EN_CONCERTACION` 409 · `PLAN_NO_ESTA_EN_FIRMAS` 409 · `PLAN_NO_APROBADO` 409 · `PLAN_MODIFICADO` 409 ·
`AJUSTE_EN_NEGOCIACION` 409 · `NEGOCIACION_ESTADO_INVALIDO` 409 · `NEGOCIACION_NO_ESCALADA` 409 · `FIRMA_YA_REGISTRADA` 409 · `FIRMA_FUERA_DE_ORDEN` 409 · `CALENDARIO_NO_CONFIGURADO` 409 · `MATRIZ_PENDIENTE` 409 · `SIN_RESPONSABLE_PRINCIPAL` 409 · `EXPORTACION_NO_LISTA` 409 ·
`COMENTARIO_REQUERIDO` 422 · `CONFIRMACION_REQUERIDA` 422 · `DETALLE_AJUSTE_INVALIDO` 422 · `BARRERA_REQUERIDA` 422 · `BARRERA_INVALIDA` 422 · `FORTALEZA_INVALIDA` 422 · `RESPONSABLE_INVALIDO` 422 · `ASIGNATURA_INVALIDA` 422 · `FECHAS_INVALIDAS` 422 · `FECHAS_FUERA_DE_CALENDARIO` 422 · `ESTRATEGIA_INCOMPLETA` 422 · `RESULTADO_INVALIDO` 422 ·
`ACCESO_DENEGADO` 403 · `ROL_NO_PERMITIDO` 403 · `AJUSTE_NO_ES_SUYO` 403 · `ESTUDIANTE_SIN_CONSENTIMIENTO` 403 · `CONSENTIMIENTO_REQUERIDO` 403 · `EXPORTACION_EXPIRADA` 410.

## 11. Parámetros del sistema que usa el slice (`PARAMETRO_SISTEMA`)

`max_ciclos_negociacion` (3, tope 3) · `comite_inclusion_emails` (lista JSON de correos; si falta se usa `comite_inclusion_email`) · `plan_firmas_orden` · `plan_firmas_orden_estricto` (false) · `dias_expiracion_exportacion` (7).

## 12. Auditoría (LOG_AUDITORIA)

`PLAN_CREADO, PLAN_EDITADO, PLAN_ELIMINADO, PLAN_CAMBIO_ESTADO, PLAN_NUEVA_VERSION, AJUSTE_CREADO/EDITADO/ELIMINADO, AJUSTE_RESPUESTA_ESTUDIANTE, AJUSTE_ACEPTACION_DOCENTE, ESTRATEGIA_DUA_CREADA/EDITADA/ELIMINADA, FIRMA_PLAN, FIRMAS_INVALIDADAS, PLAN_VERIFICADO, NEGOCIACION, MATRIZ_F7_GENERADA, MATRIZ_F7_EDITADA, EXPORTACION_SOLICITADA, EXPORTACION_DESCARGADA`.
