"""Enumeraciones del dominio (valores en MAYUSCULAS, sin tildes/n; ver BUILD_SPEC §3).

Son `StrEnum`: se comparan directamente con strings (`user.rol == "ADMIN"`) y serializan a JSON.
En la base de datos se guardan como VARCHAR con CHECK (portable SQLite/PostgreSQL).
"""

from __future__ import annotations

from enum import StrEnum


def _vals(cls):
    return [m.value for m in cls]


# ---------------------------------------------------------------- usuarios y roles
class Rol(StrEnum):
    ADMIN = "ADMIN"
    BIENESTAR = "BIENESTAR"
    COORDINADOR = "COORDINADOR"
    DOCENTE = "DOCENTE"
    ESTUDIANTE = "ESTUDIANTE"
    FAMILIAR = "FAMILIAR"


class EstadoUsuario(StrEnum):
    PENDIENTE_ACTIVACION = "PENDIENTE_ACTIVACION"
    PENDIENTE_CONSENTIMIENTO = "PENDIENTE_CONSENTIMIENTO"
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    SUSPENDIDO = "SUSPENDIDO"


class TipoDocumento(StrEnum):
    CC = "CC"
    TI = "TI"
    PEP = "PEP"
    CE = "CE"
    PA = "PA"


class EstadoAcademico(StrEnum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    GRADUADO = "GRADUADO"
    RETIRADO = "RETIRADO"


class ViaIngreso(StrEnum):
    BIENESTAR = "BIENESTAR"  # Via 1
    AUTOIDENTIFICACION = "AUTOIDENTIFICACION"  # Via 2
    MATRICULA_CSV = "MATRICULA_CSV"  # Via 3


class FuenteSSO(StrEnum):
    LOCAL = "LOCAL"
    OIDC = "OIDC"


# ---------------------------------------------------------------- niveles genericos
class NivelBMA(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class NivelBMAC(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class NivelBajoMedioAlto(StrEnum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class Semaforo(StrEnum):
    VERDE = "VERDE"
    AMARILLO = "AMARILLO"
    ROJO = "ROJO"


class Corte(StrEnum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


class Escenario(StrEnum):
    """Los 8 escenarios del F3 (arquitectura v7 §7.1)."""

    AULA = "AULA"
    CAMPUS = "CAMPUS"
    VIRTUALIDAD = "VIRTUALIDAD"
    LABORATORIOS = "LABORATORIOS"
    PRACTICA_CLINICA = "PRACTICA_CLINICA"
    PRACTICA_SALUD_PUBLICA = "PRACTICA_SALUD_PUBLICA"
    EVENTOS = "EVENTOS"
    PASANTIAS = "PASANTIAS"


class TipoBarrera(StrEnum):
    """Los 8 tipos de barrera (RF-18)."""

    ACTITUDINAL = "ACTITUDINAL"
    COMUNICATIVA = "COMUNICATIVA"
    PEDAGOGICA = "PEDAGOGICA"
    EVALUATIVA = "EVALUATIVA"
    SENSORIAL = "SENSORIAL"
    SOCIAL = "SOCIAL"
    INSTITUCIONAL = "INSTITUCIONAL"
    TECNOLOGICA = "TECNOLOGICA"


class TipoFacilitador(StrEnum):
    """Los 5 tipos de facilitador (RF-20)."""

    PERSONAL = "PERSONAL"
    PEDAGOGICO = "PEDAGOGICO"
    SOCIAL = "SOCIAL"
    INSTITUCIONAL = "INSTITUCIONAL"
    TECNOLOGICO = "TECNOLOGICO"


class PrincipioDua(StrEnum):
    """Los 3 principios DUA (CAST 2.2)."""

    REPRESENTACION = "REPRESENTACION"
    ACCION_EXPRESION = "ACCION_EXPRESION"
    PARTICIPACION = "PARTICIPACION"


class DimensionDua(StrEnum):
    """Dimension DUA segun el ERD (§3.33)."""

    MULTIPLES_MEDIOS_PRESENTACION = "MULTIPLES_MEDIOS_PRESENTACION"
    MULTIPLES_MEDIOS_ACCION = "MULTIPLES_MEDIOS_ACCION"
    MULTIPLES_MEDIOS_PARTICIPACION = "MULTIPLES_MEDIOS_PARTICIPACION"


DIMENSION_POR_PRINCIPIO = {
    PrincipioDua.REPRESENTACION: DimensionDua.MULTIPLES_MEDIOS_PRESENTACION,
    PrincipioDua.ACCION_EXPRESION: DimensionDua.MULTIPLES_MEDIOS_ACCION,
    PrincipioDua.PARTICIPACION: DimensionDua.MULTIPLES_MEDIOS_PARTICIPACION,
}


class TipoAjuste(StrEnum):
    """Las 6 categorias de ajuste razonable (RF-22)."""

    COMUNICACION = "COMUNICACION"
    PEDAGOGIA = "PEDAGOGIA"
    EVALUACION = "EVALUACION"
    AMBIENTE = "AMBIENTE"
    INTERACCION = "INTERACCION"
    TECNOLOGIA = "TECNOLOGIA"


class DimensionResultado(StrEnum):
    """Las 9 dimensiones de resultado del MAAR-TEA."""

    ACCESO = "ACCESO"
    PARTICIPACION = "PARTICIPACION"
    APRENDIZAJE = "APRENDIZAJE"
    BIENESTAR = "BIENESTAR"
    AUTONOMIA = "AUTONOMIA"
    PERMANENCIA = "PERMANENCIA"
    PROGRESION = "PROGRESION"
    GRADUACION = "GRADUACION"
    TRANSICION = "TRANSICION"


# ---------------------------------------------------------------- consentimiento / familia / solicitudes
class EstadoConsentimiento(StrEnum):
    FIRMADO = "FIRMADO"
    REVOCADO = "REVOCADO"


class AlcanceFamiliar(StrEnum):
    CARACTERIZACION = "CARACTERIZACION"
    PLAN = "PLAN"
    SEGUIMIENTO = "SEGUIMIENTO"
    NOTIFICACIONES = "NOTIFICACIONES"  # slice C3: recibe avisos de seguimiento (HU-28); no habilita lectura de datos


class EstadoAutorizacionFamiliar(StrEnum):
    PENDIENTE = "PENDIENTE"  # invitacion enviada, el familiar aun no activa su cuenta
    VIGENTE = "VIGENTE"
    REVOCADA = "REVOCADA"
    EXPIRADA = "EXPIRADA"


class EstadoSolicitudIngreso(StrEnum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"


# ---------------------------------------------------------------- AQ-10
class ModalidadAQ10(StrEnum):
    ASISTIDA = "ASISTIDA"
    AUTOAPLICADA = "AUTOAPLICADA"


# ---------------------------------------------------------------- caracterizacion (F1)
class EstadoCaracterizacion(StrEnum):
    COMPLETA = "COMPLETA"
    INCOMPLETA = "INCOMPLETA"
    EN_REVISION = "EN_REVISION"


class NivelAutonomia(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class TipoSensorial(StrEnum):
    AUDITIVA = "AUDITIVA"
    VISUAL = "VISUAL"
    TACTIL = "TACTIL"
    OLFATIVA = "OLFATIVA"
    GUSTATIVA = "GUSTATIVA"
    VESTIBULAR = "VESTIBULAR"
    PROPIOCEPCION = "PROPIOCEPCION"


# ---------------------------------------------------------------- fortalezas (F2)
class EstadoPerfil(StrEnum):
    ACTIVO = "ACTIVO"
    ARCHIVADO = "ARCHIVADO"


class NivelConsolidacion(StrEnum):
    EMERGENTE = "EMERGENTE"
    EN_DESARROLLO = "EN_DESARROLLO"
    CONSOLIDADA = "CONSOLIDADA"


class IntensidadInteres(StrEnum):
    LEVE = "LEVE"
    MODERADO = "MODERADO"
    INTENSO = "INTENSO"
    OBSESIVO = "OBSESIVO"


class TipoEstrategiaAprendizaje(StrEnum):
    VISUAL = "VISUAL"
    AUDITIVA = "AUDITIVA"
    CINESTESICA = "CINESTESICA"
    LECTOESCRITURA = "LECTOESCRITURA"
    ESTRUCTURACION = "ESTRUCTURACION"
    RUTINA = "RUTINA"
    OTRA = "OTRA"


# ---------------------------------------------------------------- contexto (F3)
class Modalidad(StrEnum):
    PRESENCIAL = "PRESENCIAL"
    VIRTUAL = "VIRTUAL"
    HIBRIDA = "HIBRIDA"


class NivelEstructuracion(StrEnum):
    ALTAMENTE_ESTRUCTURADA = "ALTAMENTE_ESTRUCTURADA"
    MEDIANAMENTE_ESTRUCTURADA = "MEDIANAMENTE_ESTRUCTURADA"
    POCO_ESTRUCTURADA = "POCO_ESTRUCTURADA"


class DisposicionAjustes(StrEnum):
    RESISTENCIA = "RESISTENCIA"
    NEUTRA = "NEUTRA"
    RECEPTIVA = "RECEPTIVA"


class Claridad(StrEnum):
    CLARA = "CLARA"
    MEDIANAMENTE_CLARA = "MEDIANAMENTE_CLARA"
    POCO_CLARA = "POCO_CLARA"


class TiempoEvaluacion(StrEnum):
    LIMITADO = "LIMITADO"
    MEDIO = "MEDIO"
    FLEXIBLE = "FLEXIBLE"


class ModalidadClaseVirtual(StrEnum):
    SINCRONICA = "SINCRONICA"
    ASINCRONICA = "ASINCRONICA"
    MIXTA = "MIXTA"


class TipoLaboratorio(StrEnum):
    QUIMICA = "QUIMICA"
    BIOLOGIA = "BIOLOGIA"
    ANATOMIA = "ANATOMIA"
    SIMULACION_CLINICA = "SIMULACION_CLINICA"
    OTRO = "OTRO"


class TipoEvento(StrEnum):
    ACADEMICO = "ACADEMICO"
    CULTURAL = "CULTURAL"
    DEPORTIVO = "DEPORTIVO"
    OTRO = "OTRO"


class ModalidadPasantia(StrEnum):
    PRESENCIAL = "PRESENCIAL"
    REMOTA = "REMOTA"
    HIBRIDA = "HIBRIDA"


# ---------------------------------------------------------------- barreras (F4) / facilitadores (F5)
class Frecuencia(StrEnum):
    OCASIONAL = "OCASIONAL"
    FRECUENTE = "FRECUENTE"
    CONSTANTE = "CONSTANTE"


class Severidad(StrEnum):
    LEVE = "LEVE"
    MODERADA = "MODERADA"
    SEVERA = "SEVERA"


class OrigenPercibido(StrEnum):
    ESTUDIANTE = "ESTUDIANTE"
    CONTEXTO = "CONTEXTO"
    INTERACCION = "INTERACCION"


class EstadoBarrera(StrEnum):
    IDENTIFICADA = "IDENTIFICADA"
    PERSISTENTE = "PERSISTENTE"  # persiste tras aplicar DUA (paso 7)
    SUPERADA = "SUPERADA"


class TipoActitud(StrEnum):
    PREJUICIO = "PREJUICIO"
    ESTIGMA = "ESTIGMA"
    FALTA_CONOCIMIENTO = "FALTA_CONOCIMIENTO"
    SOBREPROTECCION = "SOBREPROTECCION"
    EXCLUSION = "EXCLUSION"


class AspectoEvaluativo(StrEnum):
    INSTRUCCIONES = "INSTRUCCIONES"
    TIEMPO = "TIEMPO"
    AMBIENTE = "AMBIENTE"
    FORMATO = "FORMATO"
    CRITERIOS = "CRITERIOS"


class IntensidadFacilitador(StrEnum):
    LEVE = "LEVE"
    MODERADA = "MODERADA"
    SIGNIFICATIVA = "SIGNIFICATIVA"


class Renovabilidad(StrEnum):
    FIJO = "FIJO"
    VARIABLE = "VARIABLE"
    TEMPORAL = "TEMPORAL"


class TipoRelacionSocial(StrEnum):
    AMISTAD = "AMISTAD"
    FAMILIA = "FAMILIA"
    MENTOR = "MENTOR"
    GRUPO_PARES = "GRUPO_PARES"
    COMUNIDAD = "COMUNIDAD"


class DisponibilidadTecnologia(StrEnum):
    INSTITUCIONAL = "INSTITUCIONAL"
    PERSONAL = "PERSONAL"
    GRATUITA = "GRATUITA"
    PAGO = "PAGO"


# ---------------------------------------------------------------- plan (F6)
class EstadoPlanEnum(StrEnum):
    """Maquina de estados del Plan MAAR-TEA (BUILD_SPEC §4)."""

    BORRADOR = "BORRADOR"
    EN_CONCERTACION = "EN_CONCERTACION"
    EN_NEGOCIACION = "EN_NEGOCIACION"
    ESCALADO_COMITE = "ESCALADO_COMITE"
    PENDIENTE_VALIDACION = "PENDIENTE_VALIDACION"
    PENDIENTE_FIRMAS = "PENDIENTE_FIRMAS"
    APROBADO = "APROBADO"
    IMPLEMENTACION = "IMPLEMENTACION"
    SEGUIMIENTO = "SEGUIMIENTO"
    FINALIZADO = "FINALIZADO"
    ARCHIVADO = "ARCHIVADO"


class EstadoImplementacionDua(StrEnum):
    PLANEADA = "PLANEADA"
    INICIADA = "INICIADA"
    IMPLEMENTADA = "IMPLEMENTADA"
    EVALUANDO = "EVALUANDO"


class EspecificidadAjuste(StrEnum):
    GENERAL = "GENERAL"
    PARA_ASIGNATURA = "PARA_ASIGNATURA"
    PARA_ACTIVIDAD = "PARA_ACTIVIDAD"


class EstadoAjuste(StrEnum):
    PROPUESTO = "PROPUESTO"
    ACORDADO = "ACORDADO"
    IMPLEMENTACION = "IMPLEMENTACION"
    ACTIVO = "ACTIVO"
    EVALUACION = "EVALUACION"
    MODIFICADO = "MODIFICADO"
    RETIRADO = "RETIRADO"


class TipoComunicacionAjuste(StrEnum):
    INSTRUCCIONES_ESCRITAS = "INSTRUCCIONES_ESCRITAS"
    INSTRUCCIONES_VERBALES = "INSTRUCCIONES_VERBALES"
    ANTICIPO_INFORMACION = "ANTICIPO_INFORMACION"
    COMUNICACION_CLARA = "COMUNICACION_CLARA"
    CONFIRMACION = "CONFIRMACION"
    RESUMEN_ESCRITO = "RESUMEN_ESCRITO"


class TipoPedagogicoAjuste(StrEnum):
    MATERIALES_ANTICIPADOS = "MATERIALES_ANTICIPADOS"
    METODOLOGIA_ALTERNATIVA = "METODOLOGIA_ALTERNATIVA"
    ESTRUCTURA_ADICIONAL = "ESTRUCTURA_ADICIONAL"
    TIEMPO_PROCESAMIENTO = "TIEMPO_PROCESAMIENTO"
    APRENDIZAJE_PARES = "APRENDIZAJE_PARES"
    TUTORIAS = "TUTORIAS"


class TipoEvaluativoAjuste(StrEnum):
    TIEMPO_EXTENDIDO = "TIEMPO_EXTENDIDO"
    INSTRUCCIONES_CLARAS = "INSTRUCCIONES_CLARAS"
    FORMATO_ALTERNATIVO = "FORMATO_ALTERNATIVO"
    AMBIENTE_APOYO = "AMBIENTE_APOYO"
    DESCANSOS = "DESCANSOS"
    RETROALIMENTACION_ADICIONAL = "RETROALIMENTACION_ADICIONAL"


class TipoAmbientalAjuste(StrEnum):
    ESPACIO_TRANQUILO = "ESPACIO_TRANQUILO"
    REDUCCION_ESTIMULOS = "REDUCCION_ESTIMULOS"
    ILUMINACION_MODIFICADA = "ILUMINACION_MODIFICADA"
    RUIDO_CONTROLADO = "RUIDO_CONTROLADO"
    UBICACION_ESPECIFICA = "UBICACION_ESPECIFICA"
    ELEMENTOS_SENSORIALES = "ELEMENTOS_SENSORIALES"


class TipoInteraccionAjuste(StrEnum):
    TRABAJO_INDIVIDUAL = "TRABAJO_INDIVIDUAL"
    TRABAJO_PARES = "TRABAJO_PARES"
    ESTRUCTURA_GRUPO = "ESTRUCTURA_GRUPO"
    ROL_DEFINIDO = "ROL_DEFINIDO"
    MEDIACION_DOCENTE = "MEDIACION_DOCENTE"
    TUTORIA_PARES = "TUTORIA_PARES"


class TipoTecnologicoAjuste(StrEnum):
    SOFTWARE_ACCESIBILIDAD = "SOFTWARE_ACCESIBILIDAD"
    PLATAFORMA_ALTERNATIVA = "PLATAFORMA_ALTERNATIVA"
    HERRAMIENTA_ASISTIVA = "HERRAMIENTA_ASISTIVA"
    HARDWARE_ESPECIAL = "HARDWARE_ESPECIAL"
    ACCESO_ANTICIPADO = "ACCESO_ANTICIPADO"
    SINCRONIZACION_ASINCRONICO = "SINCRONIZACION_ASINCRONICO"


class RolFirmante(StrEnum):
    ESTUDIANTE = "ESTUDIANTE"
    BIENESTAR = "BIENESTAR"
    COORDINADOR = "COORDINADOR"


class EstadoFirma(StrEnum):
    FIRMADA = "FIRMADA"
    INVALIDADA = "INVALIDADA"  # el plan cambio de version tras la firma


class TipoTareaNegociacion(StrEnum):
    OBJECION_AJUSTE = "OBJECION_AJUSTE"  # RF-25
    CONCERTACION_SEMAFORO = "CONCERTACION_SEMAFORO"  # Amarillo (RF-29)
    REDISENO_ROJO = "REDISENO_ROJO"  # Rojo (RF-39)


class EstadoTareaNegociacion(StrEnum):
    ABIERTA = "ABIERTA"
    EN_CICLO = "EN_CICLO"
    ACORDADA = "ACORDADA"
    ESCALADA_COMITE = "ESCALADA_COMITE"
    CERRADA = "CERRADA"


# ---------------------------------------------------------------- apoyos (F7)
class CategoriaApoyo(StrEnum):
    ORIENTACION_ACADEMICA = "ORIENTACION_ACADEMICA"
    TUTORIA = "TUTORIA"
    ACOMPANAMIENTO_BIENESTAR = "ACOMPANAMIENTO_BIENESTAR"  # ERD: ACOMPAÑAMIENTO_BIENESTAR
    APOYO_TRANSPORTE = "APOYO_TRANSPORTE"
    APOYO_TECNOLOGICO = "APOYO_TECNOLOGICO"
    MEDIACION_SOCIAL = "MEDIACION_SOCIAL"
    APOYO_FAMILIAR = "APOYO_FAMILIAR"


class IntensidadApoyo(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class EstadoApoyo(StrEnum):
    PLANEADO = "PLANEADO"
    INICIADO = "INICIADO"
    ACTIVO = "ACTIVO"
    SUSPENDIDO = "SUSPENDIDO"
    FINALIZADO = "FINALIZADO"


class TipoRecurso(StrEnum):
    HUMANO = "HUMANO"
    MATERIAL = "MATERIAL"
    TECNOLOGICO = "TECNOLOGICO"
    ECONOMICO = "ECONOMICO"
    TIEMPO = "TIEMPO"
    ESPACIAL = "ESPACIAL"


class DisponibilidadRecurso(StrEnum):
    DISPONIBLE = "DISPONIBLE"
    REQUIERE_ADQUISICION = "REQUIERE_ADQUISICION"
    NO_DISPONIBLE = "NO_DISPONIBLE"
    EN_ESPERA = "EN_ESPERA"


class EstadoImplementacion(StrEnum):
    EJECUTADA = "EJECUTADA"
    PENDIENTE = "PENDIENTE"
    CANCELADA = "CANCELADA"
    REPROGRAMADA = "REPROGRAMADA"


class TipoEvidenciaArchivo(StrEnum):
    DOCUMENTO = "DOCUMENTO"
    FOTO = "FOTO"
    VIDEO = "VIDEO"
    NOTA_OBSERVACION = "NOTA_OBSERVACION"


# ---------------------------------------------------------------- seguimiento (F8) / evaluacion (F9)
class TipoRegistroSeguimiento(StrEnum):
    ENTREVISTA = "ENTREVISTA"
    OBSERVACION = "OBSERVACION"
    CUESTIONARIO = "CUESTIONARIO"
    FORMULARIO = "FORMULARIO"
    NOTA = "NOTA"


class TipoEvidenciaEfectividad(StrEnum):
    ACADEMICA = "ACADEMICA"
    CONDUCTUAL = "CONDUCTUAL"
    SOCIAL = "SOCIAL"
    EMOCIONAL = "EMOCIONAL"
    PARTICIPACION = "PARTICIPACION"
    ASISTENCIA = "ASISTENCIA"


class PercepcionEstudiante(StrEnum):
    POSITIVA = "POSITIVA"
    PARCIAL = "PARCIAL"
    NEGATIVA = "NEGATIVA"


class TipoDecision(StrEnum):
    MANTENER = "MANTENER"
    MODIFICAR = "MODIFICAR"
    CREAR_NUEVO = "CREAR_NUEVO"
    RETIRAR = "RETIRAR"


class ElementoAfectado(StrEnum):
    AJUSTE = "AJUSTE"
    APOYO = "APOYO"
    ESTRATEGIA = "ESTRATEGIA"
    PLAN_COMPLETO = "PLAN_COMPLETO"


class EstadoDecision(StrEnum):
    PROPUESTA = "PROPUESTA"
    ACORDADA = "ACORDADA"
    IMPLEMENTADA = "IMPLEMENTADA"
    CANCELADA = "CANCELADA"


class EstadoNotaContinuidad(StrEnum):
    BORRADOR = "BORRADOR"
    PENDIENTE_APROBACION_ESTUDIANTE = "PENDIENTE_APROBACION_ESTUDIANTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"


class DestinatarioNota(StrEnum):
    TODOS = "TODOS"
    DOCENTE = "DOCENTE"
    COORDINADOR = "COORDINADOR"
    BIENESTAR = "BIENESTAR"


# ---------------------------------------------------------------- trayectoria
class ParticipacionClase(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    VARIABLE = "VARIABLE"


class TrabajoColaborativo(StrEnum):
    AISLADO = "AISLADO"
    CON_APOYO = "CON_APOYO"
    INDEPENDIENTE = "INDEPENDIENTE"


class BalanceVidaEstudio(StrEnum):
    DESEQUILIBRADO = "DESEQUILIBRADO"
    MEDIANO = "MEDIANO"
    EQUILIBRADO = "EQUILIBRADO"


class IndependenciaTareas(StrEnum):
    TOTAL_DEPENDENCIA = "TOTAL_DEPENDENCIA"
    PARCIAL_DEPENDENCIA = "PARCIAL_DEPENDENCIA"
    INDEPENDENCIA_PARCIAL = "INDEPENDENCIA_PARCIAL"
    TOTAL_INDEPENDENCIA = "TOTAL_INDEPENDENCIA"


class EstadoTrabajoFinal(StrEnum):
    NO_APLICA = "NO_APLICA"
    NO_INICIADO = "NO_INICIADO"
    CURSANDO = "CURSANDO"
    APROBADO = "APROBADO"
    GRADUADO = "GRADUADO"


class Satisfaccion(StrEnum):
    INSATISFECHO = "INSATISFECHO"
    NEUTRAL = "NEUTRAL"
    SATISFECHO = "SATISFECHO"
    MUY_SATISFECHO = "MUY_SATISFECHO"


class EstadoLaboral(StrEnum):
    DESEMPLEADO = "DESEMPLEADO"
    EMPLEADO_TEMPORAL = "EMPLEADO_TEMPORAL"
    EMPLEADO_FIJO = "EMPLEADO_FIJO"
    EMPRENDEDOR = "EMPRENDEDOR"
    INACTIVO = "INACTIVO"


class TipoHito(StrEnum):
    CAMBIO_SEMESTRE = "CAMBIO_SEMESTRE"
    MATERIA_CLAVE = "MATERIA_CLAVE"
    INICIO_PRACTICAS = "INICIO_PRACTICAS"
    TRABAJO_GRADO = "TRABAJO_GRADO"
    GRADUACION = "GRADUACION"
    OTRO = "OTRO"


# ---------------------------------------------------------------- academico
class NivelAcademico(StrEnum):
    TECNICO = "TECNICO"
    TECNOLOGIA = "TECNOLOGIA"
    PREGRADO = "PREGRADO"
    POSTGRADO = "POSTGRADO"


class EstadoMatricula(StrEnum):
    ACTIVA = "ACTIVA"
    SUSPENDIDA = "SUSPENDIDA"
    CANCELADA = "CANCELADA"
    COMPLETADA = "COMPLETADA"


class GradoCompromiso(StrEnum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class FuenteInasistencia(StrEnum):
    MANUAL = "MANUAL"
    SIGAA = "SIGAA"


# ---------------------------------------------------------------- DUA / CBR
class EstadoSugerencia(StrEnum):
    PROPUESTA = "PROPUESTA"
    ACEPTADA = "ACEPTADA"
    MODIFICADA = "MODIFICADA"
    RECHAZADA = "RECHAZADA"


class OrigenSugerencia(StrEnum):
    CBR = "CBR"
    FILTRO_CATALOGO = "FILTRO_CATALOGO"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------- sistema
class CanalNotificacion(StrEnum):
    PUSH = "PUSH"  # notificacion en la plataforma
    EMAIL = "EMAIL"


class EstadoEmail(StrEnum):
    PENDIENTE = "PENDIENTE"
    ENVIADO = "ENVIADO"
    ERROR = "ERROR"
    OMITIDO = "OMITIDO"  # sin SMTP configurado: queda en outbox y en logs


class TipoExportacion(StrEnum):
    PLAN_PDF = "PLAN_PDF"
    PLAN_DOCX = "PLAN_DOCX"
    MATRIZ_F7_PDF = "MATRIZ_F7_PDF"
    REPORTE_PDF = "REPORTE_PDF"
    REPORTE_XLSX = "REPORTE_XLSX"
    DATOS_ARCO = "DATOS_ARCO"
    OTRO = "OTRO"


class EstadoExportacion(StrEnum):
    SOLICITADA = "SOLICITADA"
    PROCESANDO = "PROCESANDO"
    LISTA = "LISTA"
    ERROR = "ERROR"
    EXPIRADA = "EXPIRADA"


class EspaciadoUI(StrEnum):
    NORMAL = "NORMAL"
    AMPLIO = "AMPLIO"
    MUY_AMPLIO = "MUY_AMPLIO"


class FuenteUI(StrEnum):
    PREDETERMINADA = "PREDETERMINADA"  # Atkinson Hyperlegible + Lexend
    DISLEXIA = "DISLEXIA"  # OpenDyslexic
    SISTEMA = "SISTEMA"


class TipoParametro(StrEnum):
    ENTERO = "ENTERO"
    DECIMAL = "DECIMAL"
    TEXTO = "TEXTO"
    BOOLEANO = "BOOLEANO"
    JSON = "JSON"
