# API del slice A: administración, usuarios, catálogo DUA, calendario, notificaciones, reportes y solicitudes

Prefijo `/api/v1`. Autenticación `Authorization: Bearer <jwt>` (ver `auth.md`). Errores `{"detail","code"}` en español; los 422 de
validación agregan `errores: [{campo, mensaje}]`. Paginación `?page=&page_size=` (máx. 100) → `{items,total,page,page_size}`.
Fechas ISO-8601. Roles: `ADMIN`, `BIENESTAR`, `COORDINADOR`, `DOCENTE`, `ESTUDIANTE`, `FAMILIAR`.
Errores comunes de todos los endpoints protegidos: `401 NO_AUTENTICADO/TOKEN_*`, `403 ROL_NO_PERMITIDO`.
Los `DELETE` son **bajas lógicas** (soft delete) y responden `204` sin cuerpo. Toda escritura queda en la auditoría.

Variables de entorno propias del slice: `INSTITUTIONAL_EMAIL_DOMAINS` (dominios separados por coma; `*` = cualquiera; sin definir:
`unicordoba.edu.co` en producción y `*` en desarrollo), `SOLICITUDES_RATE_LIMIT_PER_HOUR` (por defecto 5 por IP; 0 desactiva),
`JOBS_SECRET` (cron externo).

---------------------------------------------------------------------------------------------------------------------------------
## 1. Usuarios (`/usuarios`) — ADMIN; BIENESTAR solo sobre docentes

Objeto `Usuario`:
```json
{ "id": 7, "email": "x@unicordoba.edu.co", "nombre_completo": "…", "rol": "DOCENTE", "estado": "ACTIVO",
  "numero_documento": null, "tipo_documento": null, "telefono": null, "created_at": "…", "fecha_ultima_sesion": null,
  "invitacion_pendiente": false, "invitacion_vencida": false,
  "programa_id": 1, "programas_ids": [],
  "numero_empleado": null, "especialidad": null, "titulo_postgrado": null }
```
(Campos de perfil según rol: DOCENTE `programa_id, numero_empleado, especialidad, titulo_postgrado`; COORDINADOR `programas_ids`
(y `programa_id` = el primero); BIENESTAR `profesion, especializacion`; ADMIN `cargo_administrativo, area_responsable`;
ESTUDIANTE `programa_id, codigo_estudiante, via_ingreso`.) `invitacion_pendiente`: cuenta sin contraseña esperando activación;
`invitacion_vencida`: el token de 72 h ya venció (usar «reenviar invitación»).

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores (`code`) |
|---|---|---|---|---|
| `GET /usuarios` | ADMIN, BIENESTAR* | `rol, estado, q` (nombre/correo/documento), `programa_id`, `page, page_size` | `Page<Usuario>` | `403` si Bienestar pide un rol distinto de DOCENTE |
| `POST /usuarios` | ADMIN (cualquier rol de §abajo); BIENESTAR (solo DOCENTE) | `{email, nombre_completo, rol: ADMIN\|BIENESTAR\|COORDINADOR\|DOCENTE, numero_documento?, tipo_documento?: CC\|TI\|PEP\|CE\|PA, telefono?, programa_id?, programas_ids?, numero_empleado?, titulo_postgrado?, especialidad?, profesion?, especializacion?, cargo_administrativo?, area_responsable?}` | `201 Usuario` (estado `PENDIENTE_ACTIVACION`; envía invitación con token de 72 h) | `409 EMAIL_DUPLICADO`, `409 DOCUMENTO_DUPLICADO`, `422 PROGRAMA_INVALIDO`, `422 DATOS_INVALIDOS` (rol ESTUDIANTE/FAMILIAR no se crea aquí), `403` |
| `GET /usuarios/{id}` | ADMIN, BIENESTAR* | — | `Usuario` (+ `asignaciones` si es docente) | `404 USUARIO_NO_ENCONTRADO`, `403` |
| `PATCH /usuarios/{id}` | ADMIN, BIENESTAR* | parcial: `email, nombre_completo, numero_documento, tipo_documento, telefono` + campos de perfil. El rol no se edita | `Usuario` | `409 EMAIL_DUPLICADO / DOCUMENTO_DUPLICADO`, `422 PROGRAMA_INVALIDO` |
| `POST /usuarios/{id}/desactivar` | ADMIN | `{motivo?}` | `Usuario` (`estado: INACTIVO`, cierra sesiones) | `409 AUTO_DESACTIVACION`, `409 ULTIMO_ADMIN`, `409 CUENTA_YA_INACTIVA` |
| `POST /usuarios/{id}/reactivar` | ADMIN | — | `Usuario` (ACTIVO, o PENDIENTE_* si nunca activó) | `409 CUENTA_NO_INACTIVA` |
| `DELETE /usuarios/{id}` | ADMIN | `{motivo?}` (opcional) | `204` — archiva (soft delete); el correo queda reservado | `409 AUTO_DESACTIVACION / ULTIMO_ADMIN` |
| `POST /usuarios/{id}/reenviar-invitacion` | ADMIN, BIENESTAR* (también estudiantes) | — | `200 {detail, ...Usuario}`; nuevo token de 72 h (el anterior queda inválido) | `409 CUENTA_YA_ACTIVADA`, `403` (familiares) |

\* Bienestar solo gestiona cuentas con rol DOCENTE (y reenvía invitaciones a estudiantes). Ver otras cuentas → `403 ROL_NO_PERMITIDO`.

### Docentes: asignaturas (ADMIN, BIENESTAR)
| Método y ruta | Cuerpo | Respuesta | Errores |
|---|---|---|---|
| `GET /usuarios/{id}/asignaciones` | — | `{items:[{id, asignatura_id, asignatura_codigo, asignatura_nombre, semestre_academico, grupo}]}` | `422 NO_ES_DOCENTE` |
| `POST /usuarios/{id}/asignaciones` | `{asignatura_id, semestre_academico: "2026-II", grupo?}` | `201 {items:[…]}` (lista actualizada) | `409 ASIGNACION_DUPLICADA`, `404 ASIGNATURA_NO_ENCONTRADA`, `422 NO_ES_DOCENTE` |
| `DELETE /usuarios/{id}/asignaciones/{asignacion_id}` | — | `204` | `404 ASIGNACION_NO_ENCONTRADA` |

La programa del docente se asigna con `programa_id` en `POST/PATCH /usuarios`.

### Programas académicos
Objeto: `{id, nombre_programa, codigo_programa, descripcion_programa, nivel_academico: TECNICO|TECNOLOGIA|PREGRADO|POSTGRADO, duracion_semestres, total_creditos, facultad_responsable, semestre_practicas, disponibilidad_ajustes_tea, capacitacion_docentes_tea, coordinador_programa_id}`.

| Método y ruta | Roles | Cuerpo | Respuesta | Errores |
|---|---|---|---|---|
| `GET /usuarios/programas` | ADMIN, BIENESTAR, COORDINADOR | — | `{items:[Programa]}` | |
| `POST /usuarios/programas` | ADMIN | `{nombre_programa, codigo_programa, descripcion_programa?, nivel_academico?, duracion_semestres?, total_creditos?, facultad_responsable?, semestre_practicas?, disponibilidad_ajustes_tea?, capacitacion_docentes_tea?, coordinador_usuario_id?}` | `201 Programa` | `409 PROGRAMA_DUPLICADO`, `422 COORDINADOR_INVALIDO` |
| `PATCH /usuarios/programas/{id}` | ADMIN | parcial (mismos campos) | `Programa` | `404 PROGRAMA_NO_ENCONTRADO`, `409 PROGRAMA_DUPLICADO` |
| `DELETE /usuarios/programas/{id}` | ADMIN | — | `204` | `409 PROGRAMA_EN_USO` (tiene estudiantes, docentes o asignaturas) |

### Asignaturas
Objeto: `{id, programa_id, codigo, nombre, semestre_plan, creditos, escenario_predominante, es_practica}`.

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /usuarios/asignaturas` | ADMIN, BIENESTAR | `programa_id, q, page, page_size` | `Page<Asignatura>` | |
| `POST /usuarios/asignaturas` | ADMIN | `{programa_id, codigo, nombre, semestre_plan?, creditos?, escenario_predominante?, es_practica?}` | `201 Asignatura` | `409 ASIGNATURA_DUPLICADA`, `422 PROGRAMA_INVALIDO` |
| `PATCH /usuarios/asignaturas/{id}` | ADMIN | parcial | `Asignatura` | `404 ASIGNATURA_NO_ENCONTRADA`, `409 ASIGNATURA_DUPLICADA` |
| `DELETE /usuarios/asignaturas/{id}` | ADMIN | — | `204` | `409 ASIGNATURA_EN_USO` (tiene docentes asignados) |

### Vía 1 — Bienestar crea al estudiante
`POST /usuarios/estudiantes` — roles BIENESTAR, ADMIN.
Cuerpo: `{nombre_completo, codigo_estudiante, programa_id, email, telefono?, semestre_actual?, consentimiento_verbal_declarado: true}`
(`false` → `422`). Respuesta `201`: `Usuario` + `{estudiante_id, detail}`; estado `PENDIENTE_ACTIVACION` y `via_ingreso: BIENESTAR`; envía invitación
(72 h). Al activar (`/auth/activate`) pasa a `PENDIENTE_CONSENTIMIENTO`; el F0 sigue siendo obligatorio.
Errores: `409 EMAIL_DUPLICADO`, `409 CODIGO_ESTUDIANTE_DUPLICADO`, `422 CORREO_NO_INSTITUCIONAL`, `422 PROGRAMA_INVALIDO`.

---------------------------------------------------------------------------------------------------------------------------------
## 2. Solicitudes de ingreso — Vía 2 (`/solicitudes`)

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /solicitudes/programas` | público | — | `{items:[{id, nombre}]}` para el selector del formulario | |
| `POST /solicitudes/publica` | **público** (sin token) | `{codigo_estudiantil, email_institucional, nombre_completo, telefono?, programa_id?, acepta_aviso_privacidad: true, sitio_web?}` — `sitio_web` es un **honeypot**: el formulario lo debe enviar vacío (campo oculto) | `202 {detail}` **siempre el mismo texto**, exista o no el código/solicitud | `422 CORREO_NO_INSTITUCIONAL`, `422 AVISO_PRIVACIDAD_REQUERIDO`, `422 PROGRAMA_INVALIDO`, `422 DATOS_INVALIDOS`, `429 DEMASIADOS_INTENTOS` (5/hora por IP, con `Retry-After`) |
| `GET /solicitudes` | BIENESTAR, ADMIN | `estado: PENDIENTE\|APROBADA\|RECHAZADA, q, page, page_size` | `Page<Solicitud>` | |
| `POST /solicitudes/{id}/aprobar` | BIENESTAR, ADMIN | `{programa_id?}` (obligatorio si la solicitud no lo trae) | `200 {…Solicitud, detail}`; crea la cuenta (`via_ingreso: AUTOIDENTIFICACION`, `PENDIENTE_ACTIVACION`) y envía invitación de 72 h | `404 SOLICITUD_NO_ENCONTRADA`, `409 SOLICITUD_YA_RESUELTA`, `409 EMAIL_DUPLICADO / CODIGO_ESTUDIANTE_DUPLICADO`, `422 PROGRAMA_INVALIDO` |
| `POST /solicitudes/{id}/rechazar` | BIENESTAR, ADMIN | `{motivo}` (5–500; es interno, **no** se envía) | `200 Solicitud`; avisa al solicitante por correo | `409 SOLICITUD_YA_RESUELTA`, `422` |

Reglas: el solicitante nunca entra sin aprobación humana. Si el código/correo ya tiene cuenta o solicitud pendiente, o si el honeypot viene lleno,
no se crea nada y la respuesta pública es idéntica. Cada solicitud nueva notifica a Bienestar (`SOLICITUD_INGRESO_NUEVA`).
`Solicitud`: `{id, codigo_estudiantil, email_institucional, nombre_completo, telefono, programa_id, programa_nombre, estado, verificada_directorio, created_at, revisado_por_id, revisado_at, motivo_rechazo, usuario_creado_id}`.
`verificada_directorio=false` = el directorio no pudo confirmar código y correo: Bienestar decide. Adaptador: `app/services/directorio.py` (`DirectorioInstitucional`, `set_directorio()`).

---------------------------------------------------------------------------------------------------------------------------------
## 3. Importación CSV — Vía 3 (`/admin/estudiantes/…`, solo ADMIN)

* `GET /admin/estudiantes/plantilla-csv` → archivo `text/csv` (UTF-8 con BOM) con encabezados y comentarios `#`.
* `POST /admin/estudiantes/importar-csv` — `multipart/form-data` con `archivo` (CSV, máx. 2 MB / 1000 filas). Query: `dry_run` (**por defecto `true`**) y `omitir_errores` (por defecto `false`).

**Formato del CSV.** Primera fila = encabezados; separador `,` o `;`; UTF-8 o Latin-1; las líneas que empiezan con `#` y las vacías se ignoran.

| Columna | Obligatoria | Alias aceptados | Regla |
|---|---|---|---|
| `nombre_completo` | sí | nombre, nombres | máx. 255 |
| `codigo_estudiante` | sí | codigo, codigo_estudiantil | único, máx. 50 |
| `correo_institucional` | sí | correo, email | formato válido y dominio institucional |
| `programa` | sí | programa_academico, codigo_programa, carrera | código o nombre exacto de un programa existente |
| `telefono` | no | celular | |
| `semestre_actual` | no | semestre | 1–20 |
| `anio_ingreso` | no | anio | 1990–año próximo |

Respuesta `200`: `{dry_run, total_filas, validas, nuevas, ya_existentes, con_errores, errores:[{fila, campo, mensaje}], creados, omitidos, omitidos_por_error}`
(`fila` = número de línea del archivo; la 1 es el encabezado). Con `dry_run=true` **no se escribe nada**. Con `dry_run=false`:
si hay errores y no se pidió `omitir_errores=true` → `422 CSV_CON_ERRORES` (con `errores`, no se importa nada); si no, se crean las filas nuevas.
Idempotente: mismo código **y** mismo correo = `ya_existentes` (se omite sin error); código con otro correo, o correo de otra cuenta = error de esa fila.
Las cuentas nuevas quedan en `PENDIENTE_CONSENTIMIENTO` (`via_ingreso: MATRICULA_CSV`) y reciben un correo explicativo con enlace de activación (72 h) y camino al F0.
Sin F0 a los 30 días se purgan (job diario). Otros errores: `422 CSV_COLUMNAS_FALTANTES`, `422 CSV_VACIO`, `422 CSV_DEMASIADAS_FILAS`, `413 ARCHIVO_MUY_GRANDE`, `422 CSV_ILEGIBLE`.

---------------------------------------------------------------------------------------------------------------------------------
## 4. Catálogo DUA (`/catalogo-dua`) — lectura ADMIN/BIENESTAR/COORDINADOR/DOCENTE; escritura ADMIN

`Estrategia`: `{id, codigo, nombre, descripcion_pedagogica, principio: REPRESENTACION|ACCION_EXPRESION|PARTICIPACION, pauta (1-9), pauta_nombre, punto_verificacion ("7.3"), escenarios[], tipos_barrera[], perfil_estudiante, fuente, activo, created_at, updated_at}`.
`escenarios`: AULA, CAMPUS, VIRTUALIDAD, LABORATORIOS, PRACTICA_CLINICA, PRACTICA_SALUD_PUBLICA, EVENTOS, PASANTIAS. `tipos_barrera`: ACTITUDINAL, COMUNICATIVA, PEDAGOGICA, EVALUATIVA, SENSORIAL, SOCIAL, INSTITUCIONAL, TECNOLOGICA.
Pautas 1–3 son de REPRESENTACION, 4–6 de ACCION_EXPRESION, 7–9 de PARTICIPACION; el punto de verificación debe empezar por la pauta.

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /catalogo-dua/principios` | lectores | — | `{principios:[{principio, nombre, pautas:[{pauta, nombre, puntos_verificacion:[{punto, texto}]}]}], escenarios[], tipos_barrera[]}` (CAST 2.2: 3 principios, 9 pautas) | |
| `GET /catalogo-dua/estrategias` | lectores | `principio, pauta, escenario, tipo_barrera, activa, q, page, page_size`. Los no-admin solo ven activas | `Page<Estrategia>` | `422` filtro inválido |
| `GET /catalogo-dua/estrategias/{id}` | lectores | — | `Estrategia` | `404 ESTRATEGIA_NO_ENCONTRADA` |
| `POST /catalogo-dua/estrategias` | ADMIN | `{codigo, nombre, descripcion_pedagogica, principio, pauta, pauta_nombre?, punto_verificacion?, escenarios?, tipos_barrera?, perfil_estudiante?, fuente?, activo?}` | `201 Estrategia` | `409 CODIGO_DUPLICADO`, `422 ESTRATEGIA_INVALIDA` (con `errores`) |
| `PATCH /catalogo-dua/estrategias/{id}` | ADMIN | parcial | `Estrategia` | `404`, `422 ESTRATEGIA_INVALIDA` |
| `POST /catalogo-dua/estrategias/{id}/activar` · `/inactivar` | ADMIN | — | `Estrategia` | `404` |
| `DELETE /catalogo-dua/estrategias/{id}` | ADMIN | — | `204` (archiva; para solo ocultarla use `inactivar`) | `404` |
| `POST /catalogo-dua/estrategias/importar` | ADMIN | `multipart` `archivo` (CSV o JSON) + query `dry_run` (**defecto `true`**), `actualizar_existentes` (false), `omitir_errores` (false) | `{dry_run, total_filas, nuevas, actualizadas, existentes_omitidas, con_errores, errores:[{fila,campo,mensaje}], creadas, modificadas}` | `422 CSV_CON_ERRORES` (importación real con errores), `422 JSON_INVALIDO`, `422 CSV_COLUMNAS_FALTANTES`, `413` |
| `GET /catalogo-dua/estrategias/exportar` | ADMIN, BIENESTAR, COORDINADOR | `formato=json\|csv`, mismos filtros que el listado | archivo adjunto (`catalogo_dua.json` / `.csv`) | `422` |

Formato de importación. CSV con encabezados `codigo,nombre,descripcion_pedagogica,principio,pauta,pauta_nombre,punto_verificacion,escenarios,tipos_barrera,perfil_estudiante,fuente,activo`
(obligatorias: las primeras cinco; las listas se separan con `|`; `activo` = 1/0/true/false). JSON: lista de objetos o `{"estrategias":[…]}` con las mismas claves (listas como arreglos). La exportación se puede reimportar tal cual. Idempotente por `codigo`.

---------------------------------------------------------------------------------------------------------------------------------
## 5. AQ-10: configuración (`/admin/aq10`, solo ADMIN)

La **aplicación** del AQ-10 es del slice B; el slice B lee la configuración con `app.services.aq10_config.get_active_config(db)`.
Convención: una respuesta puntúa 1 cuando la `direccion` de la opción elegida coincide con `puntua_si` del ítem.

| Método y ruta | Cuerpo | Respuesta | Errores |
|---|---|---|---|
| `GET /admin/aq10` | — | `{id, version, nombre, idioma, fuente, items:[{numero 1-10, texto, puntua_si: ACUERDO\|DESACUERDO}], opciones:[{valor 1-4, etiqueta, direccion: ACUERDO\|DESACUERDO}], punto_corte, instrucciones, revision_linguistica_pendiente, activo, versiones:[{id, version, activo, created_at}]}` | `404 AQ10_NO_CONFIGURADO` |
| `PUT /admin/aq10` | `{items[10], opciones[4], instrucciones?, nombre?, idioma?, fuente?, revision_linguistica_pendiente?, punto_corte?}` | igual que el GET con la **nueva versión activa** (`"2.0"`, `"3.0"`…); la anterior queda inactiva e intacta | `422 AQ10_ITEMS_INVALIDOS` (no son 10, numeración 1–10 sin repetir, texto vacío), `422 AQ10_OPCIONES_INVALIDAS` (no son 4, valores 1–4, 2 de acuerdo y 2 de desacuerdo), `422 AQ10_PUNTO_CORTE_INVALIDO` |
| `PUT /admin/aq10/punto-corte` | `{punto_corte: 1..10}` | `{punto_corte, detail}` | `422 AQ10_PUNTO_CORTE_INVALIDO` |

Las respuestas históricas conservan su `cuestionario_id` y su `punto_corte_aplicado`. El punto de corte vive en el parámetro `aq10_punto_corte` (por defecto 6) y las instrucciones en `aq10_instrucciones`.

---------------------------------------------------------------------------------------------------------------------------------
## 6. Calendario académico y parámetros (`/calendario`)

Lectura de calendarios: cualquier usuario autenticado. Escritura: ADMIN.
`Calendario`: `{id, semestre_academico ("2026-II"), programa_id (null = institucional), fecha_inicio, fecha_fin, fecha_c1, fecha_c2, fecha_c3, fecha_inicio_practicas, umbral_inasistencia, activo, semanas_cortes:{fecha_c1:"7",…}, advertencias?[]}`.
`advertencias` (solo al crear/editar) avisa si un corte no cae en la semana habitual (C1 sem. 6–7, C2 sem. 11–12, C3 sem. 16–17); **no bloquea**.

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /calendario` | autenticado | `semestre, programa_id, solo_activos` | `{items:[Calendario]}` | |
| `GET /calendario/activo` | autenticado | `programa_id?` (usa el del programa si existe; si no, el institucional) | `Calendario` | `404 SIN_SEMESTRE_ACTIVO` |
| `POST /calendario` | ADMIN | `{semestre_academico, programa_id?, fecha_inicio, fecha_fin, fecha_c1, fecha_c2, fecha_c3, fecha_inicio_practicas?, umbral_inasistencia? (defecto: parámetro), activo?}` | `201 Calendario` | `409 CALENDARIO_DUPLICADO`, `422 CALENDARIO_INVALIDO` (fin>inicio; inicio<C1<C2<C3≤fin; prácticas dentro del semestre), `422 PROGRAMA_INVALIDO` |
| `PATCH /calendario/{id}` | ADMIN | parcial | `Calendario` | `404 CALENDARIO_NO_ENCONTRADO`, `422 CALENDARIO_INVALIDO` |
| `POST /calendario/{id}/activar` | ADMIN | — | `Calendario` (desactiva el activo del mismo ámbito) | `404` |
| `DELETE /calendario/{id}` | ADMIN | — | `204` | `409 CALENDARIO_ACTIVO` |
| `GET /calendario/parametros` | ADMIN, BIENESTAR | — | `{items:[{clave, valor, valor_por_defecto, tipo, descripcion, minimo, maximo, modificado, updated_at}]}` | |
| `PUT /calendario/parametros/{clave}` | ADMIN | `{valor}` | `{clave, valor, anterior}`; auditado (anterior → nuevo) | `404 PARAMETRO_DESCONOCIDO`, `422 PARAMETRO_INVALIDO` |

Parámetros y rangos: `aq10_punto_corte` 1–10 (6); `umbral_inasistencia` 1–100 (20); `max_ciclos_negociacion` 1–3 (3); `dias_purga_sin_consentimiento` 7–365 (30);
`dias_recordatorio_corte_email` 1–30 (7); `dias_recordatorio_corte_push` 1–14 (1); `version_texto_f0` texto ≤20; `comite_inclusion_email` correo o vacío;
`reportes_k_minimo` 3–20 (3); `dias_negociacion_estancada` 1–90 (7); `dias_ventana_f3_inicio_semestre` 1–60 (14); `aq10_instrucciones` texto ≤2000.

---------------------------------------------------------------------------------------------------------------------------------
## 7. Notificaciones (`/notificaciones`) — solo las propias; cualquier usuario autenticado (no exige F0)

| Método y ruta | Roles | Parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /notificaciones` | autenticado | `solo_no_leidas` (bool), `page`, `page_size` | `{items:[{id, tipo, titulo, mensaje, leida, created_at, enlace}], total, no_leidas, page, page_size}` — `total` cuenta según el filtro; `no_leidas` siempre es el total sin leer del usuario | |
| `POST /notificaciones/{id}/leer` | autenticado | — | `{id, leida:true, no_leidas}` | `404 NOTIFICACION_NO_ENCONTRADA` (también si es de otro usuario) |
| `POST /notificaciones/leer-todas` | autenticado | — | `{marcadas, no_leidas: 0}` | |
| `GET /notificaciones/outbox` | ADMIN | `estado: PENDIENTE\|ENVIADO\|ERROR\|OMITIDO`, `page` | `Page<{id, destinatario_email, asunto, evento, estado, intentos, ultimo_error, created_at, enviado_at}>` (sin cuerpo del correo) | |

`enlace` es una ruta del frontend (p. ej. `/bienestar/planes/12`). No hay preferencias de canal (los canales son los de §10 M10 de la arquitectura).

---------------------------------------------------------------------------------------------------------------------------------
## 8. Salud, auditoría, jobs y cola de correo (`/admin`)

| Método y ruta | Roles | Cuerpo / parámetros | Respuesta | Errores |
|---|---|---|---|---|
| `GET /admin/salud` | ADMIN | — | `{status: ok\|degradado, version, entorno, base_de_datos:{ok, motor, latencia_ms}, conteos:{usuarios_activos, usuarios_pendientes, planes_vigentes, notificaciones_no_leidas, registros_auditoria}, cola_email:{pendientes, fallidas, omitidas, enviadas_24h, ultimos_errores:[{id, asunto, intentos, error}]}, ultimos_errores:[{fecha, origen, mensaje}], tareas:{modo: celery\|en_linea, broker_configurado, ultimo_job_diario:{fecha, errores}\|null, jobs_secret_configurado}, correo: smtp\|outbox, almacenamiento, generado_at}` | |
| `GET /admin/auditoria` | ADMIN | `actor_id, actor_rol, accion, entidad, entidad_id, desde, hasta` (fechas AAAA-MM-DD, UTC), `page, page_size` | `Page<{id, created_at, actor_id, actor_rol, accion, entidad, entidad_id, estudiante_id, ip, request_id, detalle}>` más recientes primero. El `detalle` nunca trae respuestas, puntajes, diagnósticos, textos ni tokens (se muestran como `"***"`) | |
| `GET /admin/auditoria/acciones` | ADMIN | — | `{items:["ACCESO_AQ10", …]}` para el filtro | |
| `POST /admin/jobs/run-daily` | header `X-Jobs-Secret: <JOBS_SECRET>` **o** ADMIN autenticado | query `hoy` (AAAA-MM-DD, para simular una fecha) | `{ejecutado_at, hoy, origen: "secreto"\|"admin:<id>", resultados:{<job>:{afectados, …}\|{error}}, errores}` | `401 JOBS_SECRET_REQUERIDO` (sin secreto ni sesión), `401 JOBS_SECRET_INVALIDO` (también si el servidor no tiene `JOBS_SECRET`), `403` (no admin) |
| `POST /admin/email-outbox/reintentar` | ADMIN | `{ids?: [], limite?: 100}` (sin `ids` reintenta los `ERROR`) | `{reintentados, enviados, con_error, omitidos, smtp_configurado, detail}` | |

Jobs de `resultados`: `recordatorios_corte` (7 d correo, 1 d push a Bienestar, estudiantes con plan vigente y docentes responsables; detalle `C1_7d`, `C2_1d`…),
`inicio_semestre_f3` (`estudiantes_pendientes`), `semestre_practicas`, `vencimiento_invitaciones` (`invitaciones_estudiantes`, `invitaciones_otros`, `autorizaciones_expiradas`),
`negociaciones_estancadas`, `vencimiento_exportaciones` (slice C1), `purga_sin_consentimiento` (30 d). Todos idempotentes (dedupe por corte+usuario+tipo). Con Celery beat corre a diario 06:00 (America/Bogota); sin worker, usar cron externo contra este endpoint.

---------------------------------------------------------------------------------------------------------------------------------
## 9. Reportes institucionales (`/reportes`) — ADMIN y COORDINADOR (coordinador: solo sus programas); uso del sistema: solo ADMIN

**Privacidad (RF-36):** solo datos agregados, sin identificadores. Toda celda con `0 < n < k` se devuelve `null` (k = `reportes_k_minimo`, mínimo 3), con supresión complementaria
en distribuciones que suman un total. El cero no se oculta. Los conteos son de estudiantes distintos. Cada respuesta incluye la cabecera
`{k_minimo, generado_at, alcance:{rol, programas:[{id,nombre}]}, filtros, nota_privacidad, celdas_suprimidas}`.
Un coordinador que pide un programa ajeno recibe `403 PROGRAMA_FUERA_DE_ALCANCE`. Filtros comunes: `programa_id`, `semestre` ("2026-II").

| Método y ruta | Parámetros extra | Respuesta (además de la cabecera) |
|---|---|---|
| `GET /reportes/alcance` | — | `{k_minimo, programas:[{id,nombre}]}` |
| `GET /reportes/dashboard` | | `programas:[{programa_id, programa, planes_activos, semaforo:{VERDE,AMARILLO,ROJO,SIN_REGISTRO}, tipos_barrera:{<TIPO>:n}, permanencia:{continuan, no_continuan, tasa_permanencia_pct}}]`, `totales:{mismos campos}` |
| `GET /reportes/trayectorias` | `ref_permanencia, ref_avance, ref_graduacion (0-100), ref_promedio (0-5)` reemplazan la referencia guardada solo en esa consulta | `programas:[{programa_id, programa, estudiantes_con_trayectoria, permanencia:{continuan,no_continuan}, indicadores:{permanencia_pct, avance_promedio_pct, graduacion_pct, promedio_academico: {cohorte_tea, referencia_programa, diferencia}}, referencia_fuente}]` |
| `GET /reportes/ajustes-frecuentes` | `top` (15) | `categorias:[{categoria, estudiantes, ajustes}]`, `categorias_ocultas`, `ajustes_especificos:[{categoria, tipo, estudiantes, ajustes}]`, `ajustes_especificos_ocultos` (las filas con n<k no se listan) |
| `GET /reportes/efectividad-dua` | `top` (20) | `estrategias:[{estrategia_id, codigo, nombre, principio, pauta, estudiantes, tasa_implementacion_pct, casos_evaluados, tasa_efectividad_pct}]`, `estrategias_ocultas`, `por_principio:[{principio, estudiantes, tasa_implementacion_pct}]` |
| `GET /reportes/uso` (ADMIN) | `desde, hasta` (defecto: últimos 180 días) | `usuarios_por_rol_estado`, `estudiantes_por_via_ingreso`, `planes_por_estado`, `planes_por_semestre:[{semestre, planes_generados, semaforo}]`, `actividad:{inicios_de_sesion, notificaciones_creadas, correos_por_estado, exportaciones_por_tipo}` |
| `GET /reportes/referencias` | — | `{items:[{programa_id, programa, permanencia_pct, avance_promedio_pct, graduacion_pct, promedio_academico, fuente}]}` |
| `PUT /reportes/referencias/{programa_id}` (ADMIN) | cuerpo `{permanencia_pct?, avance_promedio_pct?, graduacion_pct? (0-100), promedio_academico? (0-5), fuente?}` | el mismo objeto; `404 PROGRAMA_NO_ENCONTRADO`, `422` |
| `GET /reportes/{tipo}/export` | `formato=xlsx\|pdf` (defecto `xlsx`) + los filtros del reporte; `tipo` ∈ `dashboard, trayectorias, ajustes-frecuentes, efectividad-dua, uso` | archivo adjunto: `.xlsx` (hoja «Resumen» + una por tabla) o `.pdf` (WeasyPrint). Si el servidor no puede generar PDF devuelve **HTML imprimible** (`Content-Type: text/html`, cabeceras `X-Export-Degradado: html` y `X-Export-Aviso`). Errores: `404 REPORTE_NO_ENCONTRADO`, `403`, `422 formato`. La exportación queda auditada (`EXPORTACION_SOLICITADA`). |

---------------------------------------------------------------------------------------------------------------------------------
## 10. Notas de integración

* Migración propia `alembic/versions/20261116_00A1_slice_a.py` (revisión `00A1`, hija de `0001`): agrega `calendario_academico.fecha_inicio_practicas` (nullable). Si varios slices crean migraciones hijas de `0001`, el orquestador debe fusionar las cabezas (`alembic merge`).
* `scripts/seed_extra_a.py::seed(db, demo=None)`: parámetros del slice, instrucciones del AQ-10, asignaturas de ejemplo y (demo) una solicitud pendiente y una referencia del programa. Idempotente.
* Servicios reutilizables: `services/aq10_config.get_active_config(db)`, `services/system_params.get_value/k_minimo`, `services/student_intake` (alta de estudiante por las tres vías), `services/messaging` (correo/push fuera del catálogo), `services/directorio` (adaptador del directorio institucional).
