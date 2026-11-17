# Modelo de datos del backend STI

Fuente: `docs/ERD_Modelo_Datos_STI.md` (69 entidades, §3.1–3.69), `sti/BUILD_SPEC.md` §3–4 y arquitectura v7 §7, §10, §12.
Código: `app/models/` (SQLAlchemy 2.0, portable SQLite/PostgreSQL 16). Migración inicial: `alembic/versions/*_0001_esquema_inicial.py`.

## Conteo final

| Grupo | Tablas |
|---|---|
| Entidades del ERD (§3.1–3.69), todas implementadas | 69 |
| Escenarios F3 de la v7 que el ERD no detallaba (virtualidad, laboratorio, práctica clínica, práctica de salud pública, evento, pasantía) | 6 |
| Entidades exigidas por BUILD_SPEC §4 / v7 (CONSENTIMIENTO, CUESTIONARIO_AQ10, RESPUESTA_AQ10, TAREA_NEGOCIACION, LOG_AUDITORIA, ESTRATEGIA_DUA_CATALOGO, SUGERENCIA_DUA, CASO_CBR, CALENDARIO_ACADEMICO, PARAMETRO_SISTEMA, NOTIFICACION, EMAIL_OUTBOX, AUTORIZACION_FAMILIAR, FIRMA_PLAN, PLAN_VERSION, REGISTRO_SEGUIMIENTO_AJUSTE, ASIGNATURA, ASIGNACION_DOCENTE, SOLICITUD_INGRESO, NOTA_CONTINUIDAD, PREFERENCIA_SENSORIAL_UI, REFRESH_TOKEN, EXPORTACION) | 23 |
| Adicionales de la base (HITO_TRAYECTORIA: hitos de M8; REGISTRO_INASISTENCIA: RF-31 / registro manual de Bienestar) | 2 |
| **TOTAL de tablas de negocio** | **100** (+ `alembic_version` = 101 en la BD) |

## Convenciones

* PK entera autoincremental llamada **`id`** (en el ERD `plan_id`, `barrera_id`... → siempre `id` en el modelo/API).
* **Todas** las tablas: `id`, `created_at`, `updated_at` y soft delete (`deleted_at`, `deleted_reason`, `deleted_by_id`),
  excepto `LOG_AUDITORIA` (solo anexo: `id`, `created_at`) y `REFRESH_TOKEN` (`id`, `created_at`).
  Las consultas ORM **excluyen automáticamente** los eliminados; para verlos: `select(...).execution_options(include_deleted=True)`.
  El `DELETE` físico lanza `HardDeleteForbidden`, salvo `ESTADO_PLAN` y la purga legal (`services/jobs.purge_unconsented_accounts`).
* Enums = `VARCHAR` + `CHECK ck_<tabla>_<columna>` (no nativos; portables). Valores en MAYÚSCULAS sin tildes/ñ
  (`ACOMPAÑAMIENTO_BIENESTAR` → `ACOMPANAMIENTO_BIENESTAR`; `año_ingreso` → `anio_ingreso`; `años_*` → `anios_*`; `dimensión_*` → `dimension_*`).
  Definidos en `app/models/enums.py` (`StrEnum`: se comparan con strings).
* Listas del ERD guardadas como VARCHAR separado por comas (`profesionales_responsables_ids`, `participantes_ids`,
  `asistentes_ids`, `programa_responsable_ids`, `transiciones_permitidas`) → **JSON** (`JSON` portable; `JSONB` solo como variante PostgreSQL).
* `LONGBLOB` del ERD (`evidencia_digitalizada`, `documento_adjunto`) → referencia a almacenamiento (`archivo_key`, `archivo_nombre`,
  `archivo_content_type`, `archivo_size`; R2 o disco local vía `services/storage.py`).
* Fechas/horas: `DATETIME` con zona, siempre UTC (`UTCDateTime`).

## Cifrado en reposo (AES-256-GCM, clave `DATA_ENCRYPTION_KEY`)

Formato `v1:` + base64url(nonce‖ciphertext‖tag). TypeDecorators `EncryptedText`, `EncryptedJSON`, `EncryptedDate` (`app/core/crypto.py`).

| Dato | Campo |
|---|---|
| Respuestas y puntaje AQ-10 | `respuesta_aq10.respuestas`, `respuesta_aq10.puntaje` (el booleano `supera_umbral` va en claro para el flujo RF-10) |
| Narrativas F1 | `caracterizacion.resumen_ejecutivo`, `autodescripcion_estudiante` |
| Datos de comunicación / sensoriales / autonomía / preferencias (F1) | todos los textos de `dato_comunicacion`, `dato_sensorial`, `dato_autonomia`, `dato_preferencia` |
| Notas de continuidad F10 | `nota_continuidad.contenido` |
| Diagnóstico | `estudiante.fecha_diagnostico_tea`, `tipo_tea_caracterizacion`, `institucion_diagnostico` |

Límite conocido: no se puede filtrar/ordenar/buscar por columnas cifradas (solo leer y escribir).

## Reconciliación de los 8 escenarios de la v7 con las 7 subentidades del ERD (F3)

El ERD (diagrama §2) nombra 7 subentidades de CONTEXTO_UNIVERSITARIO — AULA, DOCENTE, EVALUACION, CAMPUS, VIRTUALIDAD, PRACTICA, BIENESTAR —
y solo detalla atributos de AULA, DOCENTE, EVALUACION y CAMPUS (§3.13–3.16). La v7 (§7.1, §12, RF-17) exige **8 escenarios**: aula, campus,
virtualidad, laboratorios, prácticas clínicas, prácticas de salud pública, eventos y pasantías. No son el mismo eje.

Decisión (documentada también en `app/models/contexto.py`):

1. **8 tablas, una por escenario v7**: `contexto_aula`, `contexto_campus` (atributos del ERD), `contexto_virtualidad`, `contexto_laboratorio`,
   `contexto_practica_clinica`, `contexto_practica_salud_publica`, `contexto_evento`, `contexto_pasantia` (nuevas, mismo patrón:
   campos comunes `aplica`, `descripcion_condiciones`, `metodologias_docentes`, `dinamicas_evaluacion`, `observaciones` + atributos propios).
2. `contexto_docente` y `contexto_evaluacion` se **conservan tal cual el ERD** como *facetas transversales* (no son escenarios).
3. `CONTEXTO_PRACTICA` del ERD se **divide** en clínica y salud pública. `CONTEXTO_BIENESTAR` (sin atributos en el ERD) se **absorbe** en
   `contexto_campus` (`servicios_bienestar`).
4. Cuerpo común del F3: `contexto_universitario` (uno por estudiante y semestre, índice único parcial).
5. Los escenarios también aparecen como enum `Escenario` en `barrera_identificada.escenario`, `sugerencia_dua`, `estrategia_dua` y en el catálogo DUA.

Resultado: 11 tablas de contexto (el ERD tenía 5 detalladas).

## Otras decisiones y desviaciones respecto al ERD

* **Roles**: se usan los 6 de BUILD_SPEC (`ADMIN`, `BIENESTAR`, `COORDINADOR`, `DOCENTE`, `ESTUDIANTE`, `FAMILIAR`); el ERD tenía `ADMINISTRATIVO`/`ADMIN_SISTEMA`
  y no tenía FAMILIAR. `personal_administrativo` es el perfil del rol ADMIN. Estados de usuario: 5 de BUILD_SPEC.
* **`USUARIO`**: `tipo_documento` nullable (la carga CSV de la Vía 3 no lo trae); `fecha_registro` = `created_at`; se agregan columnas de autenticación
  (hash argon2, intentos fallidos, bloqueo, hashes de token de activación/recuperación, SSO).
* **Programa del usuario**: el ERD no pone `programa_id` en USUARIO. Vive en `estudiante.programa_id`, `docente.programa_id` y
  `coordinador_programa.programa_responsable_ids` (evita el ciclo usuario→programa→coordinador→usuario). `/auth/me.programa_id` lo resuelve por rol.
* **`PLAN_MAAR_TEA`**: el `UNIQUE(estudiante, semestre, estado)` del ERD §6.2 no garantiza «un plan activo por semestre». Se implementa como índice
  único **parcial** `(estudiante_id, semestre_academico)` sobre planes no eliminados y no `ARCHIVADO`. Las versiones son snapshots en `plan_version`.
  `estado` usa la máquina ampliada (11 estados, `services/plan_states.py`) en lugar de los 6 del ERD. `ESTADO_PLAN` es el catálogo (descripción + transiciones).
* **CHECK con subconsultas** (ERD §6.2 `ck_caracterizacion_completa`) no se pueden implementar en SQL: se validan en servicio (slice B). Sí hay CHECK:
  vigencia del plan, fechas de trayectoria, fechas de ajuste/apoyo, porcentajes 0–100, ciclo de negociación 1–3, pauta DUA 1–9, tamaño de texto UI 100/115/130.
* **`ESTRATEGIA_DUA.responsable_implementacion_id`**: nullable (ERD: NOT NULL) porque el borrador nace de sugerencias sin responsable asignado.
* **Alcance del docente**: se agregan `asignatura_id` y `responsable_id` a `ajuste_razonable`, y `asignatura_id` a `estrategia_dua`; el docente solo ve
  planes en estado vigente (APROBADO…FINALIZADO) donde tiene asignatura o responsabilidad (`ASIGNACION_DOCENTE`).
* **`BARRERA_IDENTIFICADA.tipo_barrera`** y **`FACILITADOR.tipo_facilitador`** pasan de VARCHAR libre a enum (8 y 5 valores); se agrega `escenario`,
  `estado` (IDENTIFICADA/PERSISTENTE/SUPERADA) y, en `barrera_social`, `propuesta_respuesta_institucional` (RF-19, validación en servicio).
* **Auditoría**: `log_auditoria` sin FK a usuario (sobrevive a la baja del usuario). Inmutabilidad: ORM (update/delete/bulk) + trigger en PostgreSQL.
  `consentimiento` es inmutable salvo los campos de revocación (guardia ORM).
* **JSON filtrable**: el catálogo DUA guarda `escenarios` y `tipos_barrera` como lista JSON; se filtra en servicio (portable; catálogo pequeño).

## Tabla entidad → archivo → campos clave

(Generada con `python scripts/gen_modelo_doc.py`.)

| Tabla | Clase | Archivo (`app/models/`) | Campos clave | Cifrados (AES-256-GCM) | Origen |
|---|---|---|---|---|---|
| `asignacion_docente` | `AsignacionDocente` | `academico.py` | FK docente_id, asignatura_id, semestre_academico, grupo | — | BUILD_SPEC §4 / v7 |
| `asignatura` | `Asignatura` | `academico.py` | FK programa_id, codigo, nombre | — | BUILD_SPEC §4 / v7 |
| `calendario_academico` | `CalendarioAcademico` | `academico.py` | FK programa_id, semestre_academico, fecha_inicio | — | BUILD_SPEC §4 / v7 |
| `matricula` | `Matricula` | `academico.py` | FK estudiante_id, programa_academico_id, semestre_academico, fecha_matricula | — | ERD §3.64 |
| `programa_academico` | `ProgramaAcademico` | `academico.py` | FK coordinador_programa_id, nombre_programa, codigo_programa | — | ERD §3.65 |
| `registro_inasistencia` | `RegistroInasistencia` | `academico.py` | FK estudiante_id, asignatura_id, semestre_academico, fecha_registro | — | adicional (base) |
| `apoyo` | `Apoyo` | `apoyos.py` | FK plan_id, ajuste_id, nombre_apoyo, descripcion_apoyo | — | ERD §3.41 |
| `implementacion_apoyo` | `ImplementacionApoyo` | `apoyos.py` | FK responsable_apoyo_id, fecha_implementacion, hora_inicio | — | ERD §3.45 |
| `recurso` | `Recurso` | `apoyos.py` | FK responsable_apoyo_id, responsable_provision_id, tipo_recurso, descripcion_recurso | — | ERD §3.44 |
| `registro_implementacion` | `RegistroImplementacion` | `apoyos.py` | FK implementacion_id, registrado_por_id, fecha_registro, archivo_key | — | ERD §3.46 |
| `responsable_apoyo` | `ResponsableApoyo` | `apoyos.py` | FK apoyo_id, usuario_responsable_id, cargo_responsable, porcentaje_dedicacion | — | ERD §3.43 |
| `tipo_apoyo` | `TipoApoyo` | `apoyos.py` | FK apoyo_id, categoria_apoyo | — | ERD §3.42 |
| `caracterizacion` | `Caracterizacion` | `caracterizacion.py` | FK estudiante_id, profesional_responsable_id, fecha_caracterizacion, resumen_ejecutivo | resumen_ejecutivo, autodescripcion_estudiante | ERD §3.3 |
| `dato_autonomia` | `DatoAutonomia` | `caracterizacion.py` | FK caracterizacion_id, contexto_autonomia, nivel_autonomia | actividades_autonomas, actividades_con_apoyo, actividades_supervisadas | ERD §3.5 |
| `dato_comunicacion` | `DatoComunicacion` | `caracterizacion.py` | FK caracterizacion_id, tipo_comunicacion, descripcion | descripcion, fortalezas_comunicacion, dificultades_comunicacion, estrategias_favorables | ERD §3.4 |
| `dato_preferencia` | `DatoPreferencia` | `caracterizacion.py` | FK caracterizacion_id, tipo_preferencia, descripcion | descripcion, razon_preferencia | ERD §3.7 |
| `dato_sensorial` | `DatoSensorial` | `caracterizacion.py` | FK caracterizacion_id, tipo_sensorial, hipersensibilidad | descripcion_experiencia, impacto_academico, estrategias_autoregulacion | ERD §3.6 |
| `estrategia_aprendizaje` | `EstrategiaAprendizaje` | `caracterizacion.py` | FK perfil_fortalezas_id, nombre_estrategia, descripcion | — | ERD §3.11 |
| `fortaleza` | `Fortaleza` | `caracterizacion.py` | FK perfil_fortalezas_id, nombre_fortaleza, descripcion_detallada | — | ERD §3.9 |
| `interes` | `Interes` | `caracterizacion.py` | FK perfil_fortalezas_id, nombre_interes, descripcion | — | ERD §3.10 |
| `perfil_fortalezas` | `PerfilFortalezas` | `caracterizacion.py` | FK estudiante_id, profesional_responsable_id, fecha_elaboracion, narrativa_fortalezas | — | ERD §3.8 |
| `autorizacion_familiar` | `AutorizacionFamiliar` | `consentimiento.py` | FK estudiante_id, familiar_usuario_id, familiar_nombre, familiar_email | — | BUILD_SPEC §4 / v7 |
| `consentimiento` | `Consentimiento` | `consentimiento.py` | FK estudiante_id, firmado_por_id, version_texto, texto_hash | — | BUILD_SPEC §4 / v7 |
| `cuestionario_aq10` | `CuestionarioAQ10` | `consentimiento.py` | nombre, version | — | BUILD_SPEC §4 / v7 |
| `respuesta_aq10` | `RespuestaAQ10` | `consentimiento.py` | FK estudiante_id, cuestionario_id, modalidad, aplicado_at | respuestas, puntaje | BUILD_SPEC §4 / v7 |
| `solicitud_ingreso` | `SolicitudIngreso` | `consentimiento.py` | FK programa_id, revisado_por_id, codigo_estudiantil, email_institucional | — | BUILD_SPEC §4 / v7 |
| `contexto_aula` | `ContextoAula` | `contexto.py` | FK contexto_universitario_id, numero_estudiantes, tipo_aula | — | ERD §3.13 |
| `contexto_campus` | `ContextoCampus` | `contexto.py` | FK contexto_universitario_id, accesibilidad_fisica, disponibilidad_espacios_tranquilos | — | ERD §3.16 |
| `contexto_docente` | `ContextoDocente` | `contexto.py` | FK contexto_universitario_id, docente_id, nombre_docente, estilo_pedagogico | — | ERD §3.14 |
| `contexto_evaluacion` | `ContextoEvaluacion` | `contexto.py` | FK contexto_universitario_id, tipos_evaluacion_usados, claridad_criterios | — | ERD §3.15 |
| `contexto_evento` | `ContextoEvento` | `contexto.py` | FK contexto_universitario_id, tipo_evento, aforo_estimado | — | v7 §7.1 (escenario F3) |
| `contexto_laboratorio` | `ContextoLaboratorio` | `contexto.py` | FK contexto_universitario_id, tipo_laboratorio, aforo | — | v7 §7.1 (escenario F3) |
| `contexto_pasantia` | `ContextoPasantia` | `contexto.py` | FK contexto_universitario_id, organizacion, sector | — | v7 §7.1 (escenario F3) |
| `contexto_practica_clinica` | `ContextoPracticaClinica` | `contexto.py` | FK contexto_universitario_id, institucion_practica, servicio_o_area | — | v7 §7.1 (escenario F3) |
| `contexto_practica_salud_publica` | `ContextoPracticaSaludPublica` | `contexto.py` | FK contexto_universitario_id, entorno_o_comunidad, trabajo_de_campo | — | v7 §7.1 (escenario F3) |
| `contexto_universitario` | `ContextoUniversitario` | `contexto.py` | FK estudiante_id, programa_academico_id, semestre_academico, fecha_analisis | — | ERD §3.12 |
| `contexto_virtualidad` | `ContextoVirtualidad` | `contexto.py` | FK contexto_universitario_id, plataformas, modalidad_clase | — | v7 §7.1 (escenario F3) |
| `caso_cbr` | `CasoCbr` | `dua.py` | FK estrategia_catalogo_id, plan_id, perfil, resultado_semaforo | — | BUILD_SPEC §4 / v7 |
| `estrategia_dua_catalogo` | `EstrategiaDuaCatalogo` | `dua.py` | codigo, nombre | — | BUILD_SPEC §4 / v7 |
| `sugerencia_dua` | `SugerenciaDua` | `dua.py` | FK estudiante_id, plan_id, tipo_barrera, escenario | — | BUILD_SPEC §4 / v7 |
| `decision_plan` | `DecisionPlan` | `evaluacion.py` | FK evaluacion_id, responsable_decision_id, tipo_decision, elemento_afectado | — | ERD §3.52 |
| `evaluacion_plan` | `EvaluacionPlan` | `evaluacion.py` | FK plan_id, evaluador_id, fecha_evaluacion, periodo_evaluacion | — | ERD §3.51 |
| `nota_continuidad` | `NotaContinuidad` | `evaluacion.py` | FK estudiante_id, plan_id, semestre_origen, semestre_destino | contenido | BUILD_SPEC §4 / v7 |
| `barrera_actitudinal` | `BarreraActitudinal` | `mapa.py` | FK barrera_id, actores_implicados, tipo_actitud | — | ERD §3.18 |
| `barrera_comunicativa` | `BarreraComunicativa` | `mapa.py` | FK barrera_id, tipo_comunicacion_problema, descripcion_problema | — | ERD §3.19 |
| `barrera_evaluativa` | `BarreraEvaluativa` | `mapa.py` | FK barrera_id, aspecto_evaluativo, descripcion_problema | — | ERD §3.21 |
| `barrera_identificada` | `BarreraIdentificada` | `mapa.py` | FK estudiante_id, registrada_por_id, tipo_barrera, escenario | — | ERD §3.17 |
| `barrera_institucional` | `BarreraInstitucional` | `mapa.py` | FK barrera_id, politica_procedimiento, impacto_acceso | — | ERD §3.24 |
| `barrera_pedagogica` | `BarreraPedagogica` | `mapa.py` | FK barrera_id, metodologia_problematica, razon_problema | — | ERD §3.20 |
| `barrera_sensorial` | `BarreraSensorial` | `mapa.py` | FK barrera_id, tipo_sensorial, hipersensibilidad | — | ERD §3.22 |
| `barrera_social` | `BarreraSocial` | `mapa.py` | FK barrera_id, tipo_interaccion, descripcion_dificultad | — | ERD §3.23 |
| `barrera_tecnologica` | `BarreraTecnologica` | `mapa.py` | FK barrera_id, tipo_tecnologia, problema_especifico | — | ERD §3.25 |
| `facilitador` | `Facilitador` | `mapa.py` | FK estudiante_id, registrado_por_id, tipo_facilitador, nombre_facilitador | — | ERD §3.26 |
| `facilitador_institucional` | `FacilitadorInstitucional` | `mapa.py` | FK facilitador_id, politica_recurso, accesibilidad_actual | — | ERD §3.30 |
| `facilitador_pedagogico` | `FacilitadorPedagogico` | `mapa.py` | FK facilitador_id, tipo_estrategia, docentes_que_usan | — | ERD §3.28 |
| `facilitador_personal` | `FacilitadorPersonal` | `mapa.py` | FK facilitador_id, caracteristica_personal, evidencia_fortaleza | — | ERD §3.27 |
| `facilitador_social` | `FacilitadorSocial` | `mapa.py` | FK facilitador_id, tipo_relacion, actores_implicados | — | ERD §3.29 |
| `facilitador_tecnologico` | `FacilitadorTecnologico` | `mapa.py` | FK facilitador_id, tipo_tecnologia, funcionalidad_apoyo | — | ERD §3.31 |
| `ajuste_razonable` | `AjusteRazonable` | `plan.py` | FK plan_id, barrera_asociada_id, nombre_ajuste, descripcion_ajuste | — | ERD §3.34 |
| `estado_plan` | `EstadoPlan` | `plan.py` | nombre_estado, descripcion_estado | — | ERD §3.53 |
| `estrategia_dua` | `EstrategiaDua` | `plan.py` | FK plan_id, responsable_implementacion_id, nombre_estrategia, descripcion | — | ERD §3.33 |
| `firma_plan` | `FirmaPlan` | `plan.py` | FK plan_id, firmante_id, version, rol_firmante | — | BUILD_SPEC §4 / v7 |
| `plan_maar_tea` | `PlanMaarTea` | `plan.py` | FK estudiante_id, aprobado_por_id, fecha_elaboracion, profesionales_responsables_ids | — | ERD §3.32 |
| `plan_version` | `PlanVersion` | `plan.py` | FK plan_id, creado_por_id, version, estado_plan | — | BUILD_SPEC §4 / v7 |
| `respuesta_ambiente` | `RespuestaAmbiente` | `plan.py` | FK ajuste_id, tipo_ambiental_ajuste, descripcion | — | ERD §3.38 |
| `respuesta_comunicacion` | `RespuestaComunicacion` | `plan.py` | FK ajuste_id, tipo_comunicacion_ajuste, especificacion | — | ERD §3.35 |
| `respuesta_evaluacion` | `RespuestaEvaluacion` | `plan.py` | FK ajuste_id, tipo_evaluativo_ajuste, descripcion_especifica | — | ERD §3.37 |
| `respuesta_interaccion` | `RespuestaInteraccion` | `plan.py` | FK ajuste_id, tipo_interaccion_ajuste, descripcion | — | ERD §3.39 |
| `respuesta_pedagogia` | `RespuestaPedagogia` | `plan.py` | FK ajuste_id, tipo_pedagogico_ajuste, descripcion | — | ERD §3.36 |
| `respuesta_tecnologia` | `RespuestaTecnologia` | `plan.py` | FK ajuste_id, tipo_tecnologico_ajuste, descripcion_tecnologia | — | ERD §3.40 |
| `tarea_negociacion` | `TareaNegociacion` | `plan.py` | FK plan_id, ajuste_id, tipo, estado | — | BUILD_SPEC §4 / v7 |
| `evidencia_efectividad` | `EvidenciaEfectividad` | `seguimiento.py` | FK seguimiento_id, tipo_evidencia, descripcion_evidencia | — | ERD §3.49 |
| `registro_seguimiento` | `RegistroSeguimiento` | `seguimiento.py` | FK seguimiento_id, tipo_registro, descripcion_metodologia | — | ERD §3.48 |
| `registro_seguimiento_ajuste` | `RegistroSeguimientoAjuste` | `seguimiento.py` | FK seguimiento_id, ajuste_id, corte, semaforo | — | BUILD_SPEC §4 / v7 |
| `resultado_indicador` | `ResultadoIndicador` | `seguimiento.py` | FK evidencia_id, dimension_resultado, indicador_especifico | — | ERD §3.50 |
| `seguimiento` | `Seguimiento` | `seguimiento.py` | FK estudiante_id, plan_id, corte, semestre_academico | — | ERD §3.47 |
| `email_outbox` | `EmailOutbox` | `sistema.py` | FK usuario_id, notificacion_id, destinatario_email, asunto | — | BUILD_SPEC §4 / v7 |
| `exportacion` | `Exportacion` | `sistema.py` | FK solicitada_por_id, plan_id, tipo, estado | — | BUILD_SPEC §4 / v7 |
| `log_auditoria` | `LogAuditoria` | `sistema.py` | actor_id, actor_rol | — | BUILD_SPEC §4 / v7 |
| `notificacion` | `Notificacion` | `sistema.py` | FK usuario_id, tipo, titulo | — | BUILD_SPEC §4 / v7 |
| `parametro_sistema` | `ParametroSistema` | `sistema.py` | clave, valor | — | BUILD_SPEC §4 / v7 |
| `acceso` | `Acceso` | `trayectoria.py` | FK trayectoria_id, puede_ingresar_aulas, puede_usar_biblioteca | — | ERD §3.55 |
| `aprendizaje` | `Aprendizaje` | `trayectoria.py` | FK trayectoria_id, demuestra_competencias, calificaciones_promedio | — | ERD §3.57 |
| `autonomia` | `Autonomia` | `trayectoria.py` | FK trayectoria_id, gestiona_su_agenda, solicita_apoyos_autonomamente | — | ERD §3.59 |
| `bienestar` | `BienestarTrayectoria` | `trayectoria.py` | FK trayectoria_id, percepcion_bienestar, ansiedad_nivel | — | ERD §3.58 |
| `graduacion` | `Graduacion` | `trayectoria.py` | FK trayectoria_id, ha_graduado, fecha_graduacion | — | ERD §3.62 |
| `hito_trayectoria` | `HitoTrayectoria` | `trayectoria.py` | FK estudiante_id, trayectoria_id, tipo_hito, fecha_hito | — | adicional (base) |
| `participacion` | `Participacion` | `trayectoria.py` | FK trayectoria_id, asistencia_promedio, participacion_clase | — | ERD §3.56 |
| `permanencia` | `Permanencia` | `trayectoria.py` | FK trayectoria_id, continua_matriculado, riesgo_desersion | — | ERD §3.60 |
| `progresion` | `Progresion` | `trayectoria.py` | FK trayectoria_id, semestres_completados, avance_plan_estudios_porcentaje | — | ERD §3.61 |
| `transicion_profesional` | `TransicionProfesional` | `trayectoria.py` | FK trayectoria_id, experiencia_practica_laboral, horas_practica_laboral | — | ERD §3.63 |
| `trayectoria_academica` | `TrayectoriaAcademica` | `trayectoria.py` | FK estudiante_id, semestre_academico, fecha_inicio_semestre | — | ERD §3.54 |
| `coordinador_programa` | `CoordinadorPrograma` | `usuarios.py` | FK usuario_id, programa_responsable_ids, anios_en_coordinacion | — | ERD §3.67 |
| `docente` | `Docente` | `usuarios.py` | FK usuario_id, programa_id, numero_empleado, titulo_postgrado | — | ERD §3.66 |
| `estudiante` | `Estudiante` | `usuarios.py` | FK usuario_id, programa_id, codigo_estudiante, fecha_diagnostico_tea | fecha_diagnostico_tea, tipo_tea_caracterizacion, institucion_diagnostico | ERD §3.2 |
| `personal_administrativo` | `PersonalAdministrativo` | `usuarios.py` | FK usuario_id, cargo_administrativo, area_responsable | — | ERD §3.68 |
| `personal_bienestar` | `PersonalBienestar` | `usuarios.py` | FK usuario_id, profesion, especializacion | — | ERD §3.69 |
| `preferencia_sensorial_ui` | `PreferenciaSensorialUI` | `usuarios.py` | FK usuario_id, modo_calma, tamano_texto | — | BUILD_SPEC §4 / v7 |
| `refresh_token` | `RefreshToken` | `usuarios.py` | FK usuario_id, token_hash, family_id | — | BUILD_SPEC §4 / v7 |
| `usuario` | `Usuario` | `usuarios.py` | email, nombre_completo | — | ERD §3.1 |

Total: **100** tablas.
