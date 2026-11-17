"""Constructor del Plan MAAR-TEA (M5): borrador asistido (RF-21), ajustes y estrategias (RF-22), matriz F7 (RF-26) y
métrica de tasa de implementación (D6).

El borrador combina: barreras persistentes (F4), facilitadores (F5), fortalezas (F2) y sugerencias DUA ACEPTADAS/MODIFICADAS
(M3). Cada ajuste/estrategia candidato queda enlazado a la barrera que resuelve y a la fortaleza en que se apoya; el
Estudiante y Bienestar lo revisan (nada queda firme sin concertación).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.models.academico import Asignatura, CalendarioAcademico, Matricula
from app.models.apoyos import (
    Apoyo,
    ImplementacionApoyo,
    Recurso,
    ResponsableApoyo,
    TipoApoyo,
)
from app.models.base import utcnow
from app.models.caracterizacion import Fortaleza, PerfilFortalezas
from app.models.dua import EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import (
    DIMENSION_POR_PRINCIPIO,
    CategoriaApoyo,
    Corte,
    DimensionDua,
    DisponibilidadRecurso,
    EspecificidadAjuste,
    EstadoAjuste,
    EstadoApoyo,
    EstadoBarrera,
    EstadoImplementacion,
    EstadoPlanEnum,
    EstadoSugerencia,
    IntensidadApoyo,
    Rol,
    Severidad,
    TipoAjuste,
    TipoBarrera,
    TipoComunicacionAjuste,
    TipoEvaluativoAjuste,
    TipoInteraccionAjuste,
    TipoPedagogicoAjuste,
    TipoRecurso,
    TipoTecnologicoAjuste,
)
from app.models.enums import TipoAmbientalAjuste as TAmb
from app.models.mapa import BarreraIdentificada, BarreraSensorial, Facilitador
from app.models.plan import AjusteRazonable, EstrategiaDua, PlanMaarTea
from app.models.usuarios import Estudiante, Usuario
from app.services import plan_categorias as cats
from app.services import plan_common as common
from app.services import plan_workflow as wf
from app.services.plan_states import ESTADOS_ACTIVOS, ESTADOS_VIGENTES

logger = logging.getLogger("sti.plan_builder")

META_TASA_IMPLEMENTACION = 80.0  # D6: >= 80 % al C2

# ----------------------------------------------------------------------------- plantillas del borrador (deterministas)
#: tipo de barrera -> (categoría de ajuste, tipo de detalle por defecto)
BARRERA_A_AJUSTE: dict[TipoBarrera, tuple[TipoAjuste, str]] = {
    TipoBarrera.ACTITUDINAL: (TipoAjuste.INTERACCION, TipoInteraccionAjuste.MEDIACION_DOCENTE.value),
    TipoBarrera.COMUNICATIVA: (TipoAjuste.COMUNICACION, TipoComunicacionAjuste.INSTRUCCIONES_ESCRITAS.value),
    TipoBarrera.PEDAGOGICA: (TipoAjuste.PEDAGOGIA, TipoPedagogicoAjuste.MATERIALES_ANTICIPADOS.value),
    TipoBarrera.EVALUATIVA: (TipoAjuste.EVALUACION, TipoEvaluativoAjuste.TIEMPO_EXTENDIDO.value),
    TipoBarrera.SENSORIAL: (TipoAjuste.AMBIENTE, TAmb.REDUCCION_ESTIMULOS.value),
    TipoBarrera.SOCIAL: (TipoAjuste.INTERACCION, TipoInteraccionAjuste.ESTRUCTURA_GRUPO.value),
    TipoBarrera.INSTITUCIONAL: (TipoAjuste.PEDAGOGIA, TipoPedagogicoAjuste.ESTRUCTURA_ADICIONAL.value),
    TipoBarrera.TECNOLOGICA: (TipoAjuste.TECNOLOGIA, TipoTecnologicoAjuste.SOFTWARE_ACCESIBILIDAD.value),
}
_SENSORIAL_A_DETALLE = {
    "AUDITIVA": TAmb.RUIDO_CONTROLADO.value, "VISUAL": TAmb.ILUMINACION_MODIFICADA.value,
    "TACTIL": TAmb.ELEMENTOS_SENSORIALES.value, "OLFATIVA": TAmb.ESPACIO_TRANQUILO.value,
    "VESTIBULAR": TAmb.UBICACION_ESPECIFICA.value,
}
_TEXTO_AJUSTE: dict[TipoAjuste, tuple[str, str, str]] = {
    # categoría -> (nombre corto, descripción base, indicador de efectividad)
    TipoAjuste.COMUNICACION: (
        "Comunicación clara y anticipada",
        "Entregar las indicaciones y los cambios de forma clara, por escrito y con anticipación.",
        "El estudiante reporta que entiende las indicaciones sin tener que pedirlas varias veces.",
    ),
    TipoAjuste.PEDAGOGIA: (
        "Apoyo pedagógico estructurado",
        "Compartir materiales con anticipación y estructurar las actividades en pasos claros.",
        "El estudiante llega preparado a las sesiones y completa las actividades en los tiempos acordados.",
    ),
    TipoAjuste.EVALUACION: (
        "Condiciones de evaluación accesibles",
        "Ajustar el tiempo, el formato o las instrucciones de las evaluaciones, sin cambiar lo que se evalúa.",
        "El estudiante puede demostrar lo aprendido sin que las condiciones de la prueba lo bloqueen.",
    ),
    TipoAjuste.AMBIENTE: (
        "Ambiente de menor estimulación",
        "Ofrecer un espacio o ubicación con menos estímulos sensoriales durante las actividades.",
        "El estudiante reporta menos sobrecarga sensorial y mantiene la participación en clase.",
    ),
    TipoAjuste.INTERACCION: (
        "Interacción estructurada",
        "Definir roles y estructura para el trabajo en grupo, con mediación docente cuando se necesite.",
        "El estudiante participa en el trabajo grupal con roles claros y sin situaciones de exclusión.",
    ),
    TipoAjuste.TECNOLOGIA: (
        "Apoyo tecnológico accesible",
        "Habilitar el software o la plataforma alternativa que reduce la barrera de acceso.",
        "El estudiante accede a la plataforma y a los materiales sin ayuda adicional.",
    ),
}
_TIPO_RECURSO_POR_CATEGORIA = {
    TipoAjuste.COMUNICACION: TipoRecurso.TIEMPO, TipoAjuste.PEDAGOGIA: TipoRecurso.MATERIAL,
    TipoAjuste.EVALUACION: TipoRecurso.TIEMPO, TipoAjuste.AMBIENTE: TipoRecurso.ESPACIAL,
    TipoAjuste.INTERACCION: TipoRecurso.HUMANO, TipoAjuste.TECNOLOGIA: TipoRecurso.TECNOLOGICO,
}
_CATEGORIA_APOYO = {
    TipoAjuste.COMUNICACION: CategoriaApoyo.ORIENTACION_ACADEMICA, TipoAjuste.PEDAGOGIA: CategoriaApoyo.TUTORIA,
    TipoAjuste.EVALUACION: CategoriaApoyo.ORIENTACION_ACADEMICA,
    TipoAjuste.AMBIENTE: CategoriaApoyo.ACOMPANAMIENTO_BIENESTAR,
    TipoAjuste.INTERACCION: CategoriaApoyo.MEDIACION_SOCIAL, TipoAjuste.TECNOLOGIA: CategoriaApoyo.APOYO_TECNOLOGICO,
}
_FACILITADOR_POR_BARRERA = {
    TipoBarrera.TECNOLOGICA: {"TECNOLOGICO"}, TipoBarrera.PEDAGOGICA: {"PEDAGOGICO"}, TipoBarrera.EVALUATIVA: {"PEDAGOGICO"},
    TipoBarrera.SOCIAL: {"SOCIAL"}, TipoBarrera.ACTITUDINAL: {"SOCIAL", "INSTITUCIONAL"},
    TipoBarrera.INSTITUCIONAL: {"INSTITUCIONAL"}, TipoBarrera.COMUNICATIVA: {"PERSONAL", "PEDAGOGICO"},
    TipoBarrera.SENSORIAL: {"INSTITUCIONAL", "PERSONAL"},
}
_STOP = {"de", "la", "el", "los", "las", "en", "y", "a", "un", "una", "con", "por", "para", "que", "del", "al", "se", "su", "es"}


def _tokens(texto: str | None) -> set[str]:
    if not texto:
        return set()
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z]{4,}", t) if w not in _STOP}


def _recorta(texto: str | None, n: int) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


# ----------------------------------------------------------------------------- lectura de insumos
def barreras_candidatas(db: Session, estudiante_id: int) -> tuple[list[BarreraIdentificada], bool]:
    """Barreras PERSISTENTES (F4, paso 7). Si no hay marcadas, usa las vigentes no superadas y avisa."""
    db.flush()
    todas = list(db.scalars(select(BarreraIdentificada).where(BarreraIdentificada.estudiante_id == estudiante_id)
                            .order_by(BarreraIdentificada.id)))
    persistentes = [b for b in todas if b.estado == EstadoBarrera.PERSISTENTE]
    if persistentes:
        return persistentes, True
    return [b for b in todas if b.estado != EstadoBarrera.SUPERADA], False


def fortalezas_de(db: Session, estudiante_id: int) -> list[Fortaleza]:
    db.flush()
    perfiles = list(db.scalars(select(PerfilFortalezas.id).where(PerfilFortalezas.estudiante_id == estudiante_id)))
    if not perfiles:
        return []
    orden = {"CONSOLIDADA": 0, "EN_DESARROLLO": 1, "EMERGENTE": 2}
    fs = list(db.scalars(select(Fortaleza).where(Fortaleza.perfil_fortalezas_id.in_(perfiles)).order_by(Fortaleza.id)))
    return sorted(fs, key=lambda f: orden.get(str(f.nivel_consolidacion), 3))


def sugerencias_aceptadas(db: Session, estudiante_id: int) -> list[SugerenciaDua]:
    """Sugerencias DUA ACEPTADAS/MODIFICADAS. Usa `services.sugerencias.get_accepted` (slice B) si existe."""
    try:
        from app.services import sugerencias  # type: ignore[attr-defined]

        fn = getattr(sugerencias, "get_accepted", None)
        if fn is not None:
            res = list(fn(db, estudiante_id))
            if all(isinstance(x, SugerenciaDua) for x in res):
                return res
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - el borrador no debe fallar por el motor de sugerencias
        logger.exception("sugerencias.get_accepted falló; se leen las sugerencias del modelo")
    db.flush()
    return list(db.scalars(select(SugerenciaDua).where(
        SugerenciaDua.estudiante_id == estudiante_id,
        SugerenciaDua.estado.in_((EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA))).order_by(SugerenciaDua.id)))


def _mejor_fortaleza(fortalezas: list[Fortaleza], contexto: str) -> Fortaleza | None:
    if not fortalezas:
        return None
    ctx = _tokens(contexto)
    mejor, puntaje = None, 0
    for f in fortalezas:
        p = len(ctx & _tokens(f"{f.nombre_fortaleza} {f.descripcion_detallada} {f.areas_aplicacion or ''}"))
        if p > puntaje:
            mejor, puntaje = f, p
    return mejor or fortalezas[0]


# ----------------------------------------------------------------------------- borrador asistido
def semestre_activo(db: Session, estudiante: Estudiante) -> tuple[str | None, CalendarioAcademico | None]:
    cal = common.calendario_para(db, estudiante)
    if cal is not None:
        return cal.semestre_academico, cal
    m = db.scalar(select(Matricula).where(Matricula.estudiante_id == estudiante.id)
                  .order_by(Matricula.semestre_academico.desc(), Matricula.id.desc()))
    return (m.semestre_academico if m else None), None


def crear_borrador(db: Session, estudiante: Estudiante, actor: Usuario, *, semestre: str | None = None,
                   resumen_ejecutivo: str | None = None, justificacion_apoyos: str | None = None,
                   incluir_sugerencias: bool = True, request: Request | None = None) -> tuple[PlanMaarTea, list[str]]:
    avisos: list[str] = []
    cal = None
    if semestre is None:
        semestre, cal = semestre_activo(db, estudiante)
        if semestre is None:
            raise Conflict(
                "No hay un semestre activo: el administrador debe activar el calendario académico o el estudiante "
                "necesita una matrícula vigente. También puede indicar `semestre_academico` (p. ej. 2026-II).",
                "SEMESTRE_ACTIVO_NO_DEFINIDO")
    else:
        cal = common.calendario_para(db, estudiante, semestre)
    db.flush()
    existente = db.scalar(select(PlanMaarTea).where(
        PlanMaarTea.estudiante_id == estudiante.id, PlanMaarTea.semestre_academico == semestre,
        PlanMaarTea.estado.in_(ESTADOS_ACTIVOS)))
    if existente is not None:
        raise Conflict(
            f"Este estudiante ya tiene un Plan MAAR-TEA activo para el semestre {semestre} (estado {existente.estado}). "
            "Solo puede haber uno por semestre: continúe con ese plan o archívelo primero.",
            "PLAN_ACTIVO_EXISTENTE", extra={"plan_id": existente.id, "estado": str(existente.estado)})
    hoy = date.today()
    inicio = cal.fecha_inicio if cal else hoy
    fin = cal.fecha_fin if cal else None
    if cal is None:
        avisos.append("No hay calendario académico activo: la vigencia del plan quedó desde hoy y sin fecha de fin.")
    plan = PlanMaarTea(
        estudiante_id=estudiante.id, fecha_elaboracion=hoy, semestre_academico=semestre, vigencia_inicio=inicio,
        vigencia_fin=fin if (fin and fin > inicio) else None, resumen_ejecutivo=resumen_ejecutivo,
        justificacion_apoyos=justificacion_apoyos, estado=EstadoPlanEnum.BORRADOR, elaborado_por_id=actor.id,
        profesionales_responsables_ids=[actor.id], participacion_estudiante=True, version=1, participacion_log=[],
    )
    db.add(plan)
    db.flush()
    common.log_participacion(plan, actor, "CREO_BORRADOR", "plan", plan.id, {"semestre": semestre})

    barreras, hay_persistentes = barreras_candidatas(db, estudiante.id)
    fortalezas = fortalezas_de(db, estudiante.id)
    if not barreras:
        avisos.append("El estudiante no tiene barreras (F4) registradas: el borrador quedó sin ajustes candidatos. "
                      "Agregue los ajustes manualmente o registre primero el mapa de barreras.")
    elif not hay_persistentes:
        avisos.append("Ninguna barrera está marcada como PERSISTENTE; se usaron las barreras vigentes del mapa F4.")
    if not fortalezas:
        avisos.append("El estudiante no tiene fortalezas (F2) registradas: los ajustes quedaron sin fortaleza asociada.")

    facilitadores = list(db.scalars(select(Facilitador).where(Facilitador.estudiante_id == estudiante.id)
                                    .order_by(Facilitador.id)))
    for b in barreras:
        _ajuste_candidato(db, plan, b, fortalezas, facilitadores)

    if incluir_sugerencias:
        n = _incorporar_sugerencias(db, plan, estudiante, actor, barreras, fortalezas)
        if n == 0:
            avisos.append("No hay sugerencias DUA aceptadas por incorporar (se aceptan en el módulo de sugerencias).")
    audit.log(db, actor, common.A_PLAN_CREADO, "plan_maar_tea", plan.id,
              {"semestre": semestre, "version": plan.version}, request=request, estudiante_id=estudiante.id)
    db.flush()
    return plan, avisos


def _ajuste_candidato(db: Session, plan: PlanMaarTea, b: BarreraIdentificada, fortalezas: list[Fortaleza],
                      facilitadores: list[Facilitador]) -> AjusteRazonable:
    categoria, tipo_detalle = BARRERA_A_AJUSTE[TipoBarrera(str(b.tipo_barrera))]
    if str(b.tipo_barrera) == TipoBarrera.SENSORIAL:
        sens = db.scalar(select(BarreraSensorial).where(BarreraSensorial.barrera_id == b.id))
        if sens is not None:
            tipo_detalle = _SENSORIAL_A_DETALLE.get(str(sens.tipo_sensorial), tipo_detalle)
    nombre_base, descripcion, indicador = _TEXTO_AJUSTE[categoria]
    f = _mejor_fortaleza(fortalezas, f"{b.descripcion_barrera} {b.contexto_aparicion or ''}")
    fac = [x for x in facilitadores if str(x.tipo_facilitador) in _FACILITADOR_POR_BARRERA[TipoBarrera(str(b.tipo_barrera))]][:2]
    donde = f" en {str(b.escenario).replace('_', ' ').lower()}" if b.escenario else ""
    justif = (f"Responde a la barrera {str(b.tipo_barrera).lower()} identificada{donde}: "
              f"«{_recorta(b.descripcion_barrera, 220)}». Es una barrera del entorno que persiste tras las estrategias DUA universales.")
    if f is not None:
        justif += f" Se apoya en la fortaleza «{f.nombre_fortaleza}»."
    if fac:
        justif += " Aprovecha: " + "; ".join(f"«{x.nombre_facilitador}»" for x in fac) + "."
    ajuste = AjusteRazonable(
        plan_id=plan.id, barrera_asociada_id=b.id, nombre_ajuste=_recorta(nombre_base, 200),
        descripcion_ajuste=descripcion, justificacion=justif, tipo_ajuste=categoria,
        especificidad=EspecificidadAjuste.GENERAL, fecha_inicio=plan.vigencia_inicio,
        fecha_fin_prevista=plan.vigencia_fin, permanencia_indefinida=plan.vigencia_fin is None,
        estado=EstadoAjuste.PROPUESTO, fortaleza_apoyo_id=f.id if f else None, indicador_efectividad=indicador,
        origen="BORRADOR_ASISTIDO", propuesto_por_id=None, propuesto_por_rol="SISTEMA",
        frecuencia="Cada sesión de clase",
    )
    db.add(ajuste)
    db.flush()
    cats.escribir_detalle(db, ajuste, {"tipo": tipo_detalle, "descripcion": descripcion})
    common.log_participacion(plan, None, "PROPUSO", "ajuste", ajuste.id, {"origen": "BORRADOR_ASISTIDO"})
    return ajuste


def _incorporar_sugerencias(db: Session, plan: PlanMaarTea, estudiante: Estudiante, actor: Usuario,
                            barreras: list[BarreraIdentificada], fortalezas: list[Fortaleza]) -> int:
    ya = {e.sugerencia_id for e in db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id))
          if e.sugerencia_id}
    n = 0
    for s in sugerencias_aceptadas(db, estudiante.id):
        if s.id in ya or (s.plan_id not in (None, plan.id)):
            continue
        cat = db.get(EstrategiaDuaCatalogo, s.estrategia_catalogo_id)
        if cat is None:
            continue
        barrera = next((b for b in barreras if b.id == s.barrera_id), None) \
            or next((b for b in barreras if s.tipo_barrera and str(b.tipo_barrera) == str(s.tipo_barrera)), None)
        contexto = f"{cat.nombre} {cat.descripcion_pedagogica} {barrera.descripcion_barrera if barrera else ''}"
        f = _mejor_fortaleza(fortalezas, contexto)
        descripcion = s.texto_modificado or s.texto_accesible or cat.descripcion_pedagogica
        e = EstrategiaDua(
            plan_id=plan.id, nombre_estrategia=_recorta(cat.nombre, 200), descripcion=descripcion,
            dimension_dua=DIMENSION_POR_PRINCIPIO[s.principio_dua], alcance="Todo el grupo",
            estrategia_catalogo_id=cat.id, sugerencia_id=s.id, escenario=s.escenario or None,
            barrera_id=barrera.id if barrera else s.barrera_id, fortaleza_id=f.id if f else None,
            origen="SUGERENCIA_DUA", propuesta_por_id=actor.id, propuesta_por_rol=str(actor.rol),
            fecha_inicio_implementacion=plan.vigencia_inicio,
        )
        db.add(e)
        s.plan_id = plan.id
        db.flush()
        common.log_participacion(plan, actor, "PROPUSO", "estrategia", e.id, {"origen": "SUGERENCIA_DUA"})
        n += 1
    return n


def incorporar_sugerencias(db: Session, plan: PlanMaarTea, actor: Usuario, request: Request | None = None) -> int:
    """Agrega al plan las sugerencias DUA aceptadas desde su creación (no duplica las ya incorporadas)."""
    estudiante = common.estudiante_de(db, plan)
    barreras, _ = barreras_candidatas(db, estudiante.id)
    pendientes = [s for s in sugerencias_aceptadas(db, estudiante.id)
                  if s.plan_id in (None,) and s.estado in (EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA)]
    if not pendientes:
        return 0
    wf.preparar_edicion(db, plan, actor, "Incorporación de sugerencias DUA aceptadas", request)
    n = _incorporar_sugerencias(db, plan, estudiante, actor, barreras, fortalezas_de(db, estudiante.id))
    audit.log(db, actor, common.A_PLAN_EDITADO, "plan_maar_tea", plan.id, {"sugerencias_incorporadas": n},
              request=request, estudiante_id=plan.estudiante_id)
    return n


# ----------------------------------------------------------------------------- CRUD del plan
PLAN_CAMPOS = ("resumen_ejecutivo", "justificacion_apoyos", "vigencia_fin", "participacion_familia",
               "profesionales_responsables_ids")


def actualizar_plan(db: Session, plan: PlanMaarTea, actor: Usuario, datos: dict, request: Request | None = None) -> bool:
    cambios = {k: v for k, v in datos.items() if k in PLAN_CAMPOS and getattr(plan, k) != v}
    if "vigencia_fin" in cambios and cambios["vigencia_fin"] and cambios["vigencia_fin"] <= plan.vigencia_inicio:
        raise Unprocessable("La fecha de fin de vigencia debe ser posterior a la de inicio.", "FECHAS_INVALIDAS")
    if not cambios:
        return False
    contenido = {"resumen_ejecutivo", "justificacion_apoyos", "vigencia_fin", "participacion_familia"} & set(cambios)
    if contenido:
        wf.preparar_edicion(db, plan, actor, "Cambio en los datos generales del plan", request)
    for k, v in cambios.items():
        setattr(plan, k, v)
    common.log_participacion(plan, actor, "MODIFICO", "plan", plan.id, {"campos": sorted(cambios)})
    audit.log(db, actor, common.A_PLAN_EDITADO, "plan_maar_tea", plan.id, {"campos": sorted(cambios)}, request=request,
              estudiante_id=plan.estudiante_id)
    db.flush()
    return True


def eliminar_plan(db: Session, plan: PlanMaarTea, actor: Usuario, motivo: str, request: Request | None = None) -> None:
    if plan.estado != EstadoPlanEnum.BORRADOR:
        raise Conflict("Solo se elimina un plan en BORRADOR. Para los demás use «archivar».", "PLAN_NO_ELIMINABLE")
    plan.soft_delete(actor.id, motivo)
    audit.log(db, actor, common.A_PLAN_ELIMINADO, "plan_maar_tea", plan.id, {"motivo": motivo}, request=request,
              estudiante_id=plan.estudiante_id)
    db.flush()


# ----------------------------------------------------------------------------- validaciones de referencias
def _check_barrera(db: Session, plan: PlanMaarTea, barrera_id: int | None, *, obligatoria: bool) -> None:
    if barrera_id is None:
        if obligatoria:
            raise Unprocessable("Indique la barrera que resuelve este ajuste (es obligatoria).", "BARRERA_REQUERIDA")
        return
    b = db.get(BarreraIdentificada, barrera_id)
    if b is None or b.deleted_at is not None or b.estudiante_id != plan.estudiante_id:
        raise Unprocessable("La barrera indicada no existe o no pertenece a este estudiante.", "BARRERA_INVALIDA")


def _check_fortaleza(db: Session, plan: PlanMaarTea, fortaleza_id: int | None) -> None:
    if fortaleza_id is None:
        return
    f = db.get(Fortaleza, fortaleza_id)
    ok = False
    if f is not None and f.deleted_at is None:
        perfil = db.get(PerfilFortalezas, f.perfil_fortalezas_id)
        ok = perfil is not None and perfil.estudiante_id == plan.estudiante_id
    if not ok:
        raise Unprocessable("La fortaleza indicada no existe o no pertenece a este estudiante.", "FORTALEZA_INVALIDA")


def _check_responsable(db: Session, usuario_id: int | None) -> None:
    if usuario_id is None:
        return
    u = db.get(Usuario, usuario_id)
    if u is None or u.deleted_at is not None or str(u.rol) in (Rol.ESTUDIANTE, Rol.FAMILIAR):
        raise Unprocessable("El responsable indicado no existe o su rol no puede ser responsable de un ajuste.",
                            "RESPONSABLE_INVALIDO")


def _check_asignatura(db: Session, asignatura_id: int | None) -> Asignatura | None:
    if asignatura_id is None:
        return None
    a = db.get(Asignatura, asignatura_id)
    if a is None or a.deleted_at is not None:
        raise Unprocessable("La asignatura indicada no existe.", "ASIGNATURA_INVALIDA")
    return a


def _check_fechas(inicio: date | None, fin: date | None) -> None:
    if inicio and fin and fin < inicio:
        raise Unprocessable("La fecha de fin prevista no puede ser anterior a la de inicio.", "FECHAS_INVALIDAS")


# ----------------------------------------------------------------------------- ajustes razonables
AJUSTE_CAMPOS = (
    "nombre_ajuste", "descripcion_ajuste", "justificacion", "tipo_ajuste", "barrera_asociada_id", "fortaleza_apoyo_id",
    "responsable_id", "asignatura_id", "asignatura_si_aplica", "actividad_si_aplica", "especificidad", "recurso",
    "frecuencia", "indicador_efectividad", "fecha_inicio", "fecha_fin_prevista", "permanencia_indefinida",
)


def _normalizar_ajuste(db: Session, plan: PlanMaarTea, datos: dict, base: AjusteRazonable | None) -> dict:
    """Valida referencias y completa derivados (asignatura, especificidad). Devuelve solo lo que cambia."""
    d = {k: v for k, v in datos.items() if k in AJUSTE_CAMPOS}
    def ref(k):
        return d[k] if k in d else (getattr(base, k) if base is not None else None)

    if "barrera_asociada_id" in d or base is None:
        _check_barrera(db, plan, ref("barrera_asociada_id"), obligatoria=True)
    if "fortaleza_apoyo_id" in d:
        _check_fortaleza(db, plan, d["fortaleza_apoyo_id"])
    if "responsable_id" in d:
        _check_responsable(db, d["responsable_id"])
    asig = _check_asignatura(db, d["asignatura_id"]) if d.get("asignatura_id") else None
    if asig is not None and not d.get("asignatura_si_aplica"):
        d["asignatura_si_aplica"] = asig.nombre
    if "especificidad" not in d and any(k in d for k in ("asignatura_id", "asignatura_si_aplica", "actividad_si_aplica")):
        if ref("actividad_si_aplica"):
            d["especificidad"] = EspecificidadAjuste.PARA_ACTIVIDAD
        elif ref("asignatura_id") or ref("asignatura_si_aplica"):
            d["especificidad"] = EspecificidadAjuste.PARA_ASIGNATURA
        else:
            d["especificidad"] = EspecificidadAjuste.GENERAL
    inicio = ref("fecha_inicio") or plan.vigencia_inicio
    _check_fechas(inicio, ref("fecha_fin_prevista"))
    return d


def crear_ajuste(db: Session, plan: PlanMaarTea, actor: Usuario, datos: dict, request: Request | None = None) -> AjusteRazonable:
    detalle = cats.validar_detalle(datos["tipo_ajuste"], datos.get("detalle"))
    d = _normalizar_ajuste(db, plan, datos, None)
    wf.preparar_edicion(db, plan, actor, "Nuevo ajuste razonable", request)
    barrera = db.get(BarreraIdentificada, d["barrera_asociada_id"])
    fin = d.get("fecha_fin_prevista")
    ajuste = AjusteRazonable(
        plan_id=plan.id, nombre_ajuste=d["nombre_ajuste"], descripcion_ajuste=d["descripcion_ajuste"],
        justificacion=d.get("justificacion") or f"Responde a la barrera {str(barrera.tipo_barrera).lower()} identificada: "
                                                f"«{_recorta(barrera.descripcion_barrera, 220)}».",
        tipo_ajuste=d["tipo_ajuste"], barrera_asociada_id=d["barrera_asociada_id"],
        fortaleza_apoyo_id=d.get("fortaleza_apoyo_id"), responsable_id=d.get("responsable_id"),
        asignatura_id=d.get("asignatura_id"), asignatura_si_aplica=d.get("asignatura_si_aplica"),
        actividad_si_aplica=d.get("actividad_si_aplica"),
        especificidad=d.get("especificidad", EspecificidadAjuste.GENERAL), recurso=d.get("recurso"),
        frecuencia=d.get("frecuencia"), indicador_efectividad=d.get("indicador_efectividad"),
        fecha_inicio=d.get("fecha_inicio") or plan.vigencia_inicio, fecha_fin_prevista=fin,
        permanencia_indefinida=d.get("permanencia_indefinida", fin is None), estado=EstadoAjuste.PROPUESTO,
        origen="MANUAL", propuesto_por_id=actor.id, propuesto_por_rol=str(actor.rol),
    )
    db.add(ajuste)
    db.flush()
    cats.escribir_detalle(db, ajuste, detalle, actor.id)
    common.log_participacion(plan, actor, "PROPUSO", "ajuste", ajuste.id, {"origen": "MANUAL"})
    audit.log(db, actor, common.A_AJUSTE_CREADO, "ajuste_razonable", ajuste.id,
              {"plan_id": plan.id, "tipo_ajuste": str(ajuste.tipo_ajuste)}, request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return ajuste


def actualizar_ajuste(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, actor: Usuario, datos: dict,
                      request: Request | None = None, *, via_negociacion: bool = False) -> bool:
    if not via_negociacion and wf.tareas_abiertas(db, plan.id, ajuste.id):
        raise Conflict("Este ajuste está en negociación: use la contrapropuesta de la negociación para cambiarlo.",
                       "AJUSTE_EN_NEGOCIACION")
    nuevo_tipo = datos.get("tipo_ajuste", ajuste.tipo_ajuste)
    detalle_in = datos.get("detalle", "__sin__")
    detalle = None
    if detalle_in != "__sin__":
        detalle = cats.validar_detalle(nuevo_tipo, detalle_in)
    d = _normalizar_ajuste(db, plan, datos, ajuste)
    cambios = {k: v for k, v in d.items() if str(getattr(ajuste, k)) != str(v) and getattr(ajuste, k) != v}
    cambia_detalle = detalle_in != "__sin__" and detalle != cats.leer_detalle(db, ajuste)
    tipo_cambia = "tipo_ajuste" in cambios
    if not cambios and not cambia_detalle:
        return False
    wf.preparar_edicion(db, plan, actor, f"Cambio en el ajuste «{ajuste.nombre_ajuste}»", request)
    for k, v in cambios.items():
        setattr(ajuste, k, v)
    if tipo_cambia and detalle_in == "__sin__":
        cats.borrar_detalles(db, ajuste, actor.id, "Cambió la categoría del ajuste")
    elif cambia_detalle:
        cats.escribir_detalle(db, ajuste, detalle, actor.id)
    # el contenido cambió: el estudiante y el responsable vuelven a revisarlo
    ajuste.estado = EstadoAjuste.PROPUESTO
    ajuste.respuesta_estudiante = None
    ajuste.aceptado_por_estudiante = None
    ajuste.aceptado_por_estudiante_at = None
    ajuste.modificacion_propuesta = None
    ajuste.aceptado_por_responsable = None
    ajuste.aceptado_por_responsable_at = None
    ajuste.modificado_por_id = actor.id
    ajuste.modificado_at = utcnow()
    campos = sorted(set(cambios) | ({"detalle"} if cambia_detalle else set()))
    common.log_participacion(plan, actor, "MODIFICO", "ajuste", ajuste.id, {"campos": campos})
    audit.log(db, actor, common.A_AJUSTE_EDITADO, "ajuste_razonable", ajuste.id, {"plan_id": plan.id, "campos": campos},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return True


def eliminar_ajuste(db: Session, plan: PlanMaarTea, ajuste: AjusteRazonable, actor: Usuario, motivo: str,
                    request: Request | None = None) -> None:
    wf.preparar_edicion(db, plan, actor, f"Se retiró el ajuste «{ajuste.nombre_ajuste}»", request)
    from app.services import negotiation

    for t in wf.tareas_abiertas(db, plan.id, ajuste.id):
        negotiation.cerrar_por_retiro(db, plan, t, actor, motivo)
    ajuste.soft_delete(actor.id, motivo)
    cats.borrar_detalles(db, ajuste, actor.id, "Ajuste retirado")
    common.log_participacion(plan, actor, "ELIMINO", "ajuste", ajuste.id, {"motivo": motivo})
    audit.log(db, actor, common.A_AJUSTE_ELIMINADO, "ajuste_razonable", ajuste.id, {"plan_id": plan.id, "motivo": motivo},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()


# ----------------------------------------------------------------------------- estrategias DUA
ESTRATEGIA_CAMPOS = (
    "nombre_estrategia", "descripcion", "dimension_dua", "responsable_implementacion_id", "alcance",
    "fecha_inicio_implementacion", "estrategia_catalogo_id", "asignatura_id", "escenario", "barrera_id", "fortaleza_id",
)


def crear_estrategia(db: Session, plan: PlanMaarTea, actor: Usuario, datos: dict, request: Request | None = None) -> EstrategiaDua:
    d = {k: v for k, v in datos.items() if k in ESTRATEGIA_CAMPOS}
    cat = None
    if d.get("estrategia_catalogo_id"):
        cat = db.get(EstrategiaDuaCatalogo, d["estrategia_catalogo_id"])
        if cat is None or cat.deleted_at is not None:
            raise Unprocessable("La estrategia del catálogo DUA indicada no existe.", "CATALOGO_DUA_INVALIDO")
    nombre = d.get("nombre_estrategia") or (cat.nombre if cat else None)
    descripcion = d.get("descripcion") or (cat.descripcion_pedagogica if cat else None)
    dimension = d.get("dimension_dua") or (DIMENSION_POR_PRINCIPIO[cat.principio] if cat else None)
    if not (nombre and descripcion and dimension):
        raise Unprocessable("Indique nombre, descripción y dimensión DUA de la estrategia (o elija una del catálogo).",
                            "ESTRATEGIA_INCOMPLETA")
    _check_barrera(db, plan, d.get("barrera_id"), obligatoria=False)
    _check_fortaleza(db, plan, d.get("fortaleza_id"))
    _check_responsable(db, d.get("responsable_implementacion_id"))
    _check_asignatura(db, d.get("asignatura_id"))
    wf.preparar_edicion(db, plan, actor, "Nueva estrategia DUA", request)
    e = EstrategiaDua(
        plan_id=plan.id, nombre_estrategia=_recorta(nombre, 200), descripcion=descripcion,
        dimension_dua=DimensionDua(str(dimension)), responsable_implementacion_id=d.get("responsable_implementacion_id"),
        alcance=d.get("alcance"), fecha_inicio_implementacion=d.get("fecha_inicio_implementacion") or plan.vigencia_inicio,
        estrategia_catalogo_id=d.get("estrategia_catalogo_id"), asignatura_id=d.get("asignatura_id"),
        escenario=d.get("escenario"), barrera_id=d.get("barrera_id"), fortaleza_id=d.get("fortaleza_id"),
        origen="MANUAL", propuesta_por_id=actor.id, propuesta_por_rol=str(actor.rol),
    )
    db.add(e)
    db.flush()
    common.log_participacion(plan, actor, "PROPUSO", "estrategia", e.id, {"origen": "MANUAL"})
    audit.log(db, actor, common.A_ESTRATEGIA_CREADA, "estrategia_dua", e.id, {"plan_id": plan.id}, request=request,
              estudiante_id=plan.estudiante_id)
    return e


def actualizar_estrategia(db: Session, plan: PlanMaarTea, e: EstrategiaDua, actor: Usuario, datos: dict,
                          request: Request | None = None) -> bool:
    d = {k: v for k, v in datos.items() if k in ESTRATEGIA_CAMPOS}
    if "barrera_id" in d:
        _check_barrera(db, plan, d["barrera_id"], obligatoria=False)
    if "fortaleza_id" in d:
        _check_fortaleza(db, plan, d["fortaleza_id"])
    if "responsable_implementacion_id" in d:
        _check_responsable(db, d["responsable_implementacion_id"])
    if d.get("asignatura_id"):
        _check_asignatura(db, d["asignatura_id"])
    cambios = {k: v for k, v in d.items() if str(getattr(e, k)) != str(v) and getattr(e, k) != v}
    if not cambios:
        return False
    wf.preparar_edicion(db, plan, actor, f"Cambio en la estrategia «{e.nombre_estrategia}»", request)
    for k, v in cambios.items():
        setattr(e, k, v)
    e.modificado_por_id = actor.id
    e.modificado_at = utcnow()
    common.log_participacion(plan, actor, "MODIFICO", "estrategia", e.id, {"campos": sorted(cambios)})
    audit.log(db, actor, common.A_ESTRATEGIA_EDITADA, "estrategia_dua", e.id, {"plan_id": plan.id, "campos": sorted(cambios)},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()
    return True


def eliminar_estrategia(db: Session, plan: PlanMaarTea, e: EstrategiaDua, actor: Usuario, motivo: str,
                        request: Request | None = None) -> None:
    wf.preparar_edicion(db, plan, actor, f"Se retiró la estrategia «{e.nombre_estrategia}»", request)
    e.soft_delete(actor.id, motivo)
    if e.sugerencia_id:
        s = db.get(SugerenciaDua, e.sugerencia_id)
        if s is not None and s.plan_id == plan.id:
            s.plan_id = None
    common.log_participacion(plan, actor, "ELIMINO", "estrategia", e.id, {"motivo": motivo})
    audit.log(db, actor, common.A_ESTRATEGIA_ELIMINADA, "estrategia_dua", e.id, {"plan_id": plan.id, "motivo": motivo},
              request=request, estudiante_id=plan.estudiante_id)
    db.flush()


# ----------------------------------------------------------------------------- F7: matriz de responsabilidades
def _cortes(cal: CalendarioAcademico | None) -> list[dict]:
    if cal is None:
        return []
    return [{"corte": Corte.C1.value, "fecha": cal.fecha_c1.isoformat()},
            {"corte": Corte.C2.value, "fecha": cal.fecha_c2.isoformat()},
            {"corte": Corte.C3.value, "fecha": cal.fecha_c3.isoformat()}]


def calendario_del_plan(db: Session, plan: PlanMaarTea) -> CalendarioAcademico | None:
    return common.calendario_para(db, common.estudiante_de(db, plan), plan.semestre_academico)


def _responsables_por_defecto(db: Session, plan: PlanMaarTea, principal_id: int | None) -> tuple[int | None, int | None]:
    principal = principal_id or plan.elaborado_por_id
    secundario = None
    p = db.get(Usuario, principal) if principal else None
    if p is not None and str(p.rol) == Rol.DOCENTE:
        secundario = plan.elaborado_por_id
    elif plan.validado_por_id:
        secundario = plan.validado_por_id
    if secundario == principal:
        secundario = None
    return principal, secundario


def _apoyo_existente(db: Session, plan_id: int, *, ajuste_id: int | None = None, estrategia_id: int | None = None) -> Apoyo | None:
    stmt = select(Apoyo).where(Apoyo.plan_id == plan_id)
    stmt = stmt.where(Apoyo.ajuste_id == ajuste_id) if ajuste_id else stmt.where(Apoyo.estrategia_id == estrategia_id)
    return db.scalar(stmt.order_by(Apoyo.id))


def _asignar_responsables(db: Session, apoyo: Apoyo, principal: int | None, secundario: int | None,
                          cargo_texto: dict[int, str], frecuencia: str | None, recurso_tipo: TipoRecurso,
                          recurso_desc: str, actor_id: int | None) -> None:
    for r in db.scalars(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == apoyo.id)):
        for rec in db.scalars(select(Recurso).where(Recurso.responsable_apoyo_id == r.id)):
            rec.soft_delete(actor_id, "Matriz regenerada")
        r.soft_delete(actor_id, "Matriz regenerada")
    db.flush()
    principal_row = None
    for uid, es_principal in ((principal, True), (secundario, False)):
        if uid is None:
            continue
        r = ResponsableApoyo(
            apoyo_id=apoyo.id, usuario_responsable_id=uid, cargo_responsable=cargo_texto.get(uid),
            porcentaje_dedicacion=100 if es_principal else 25, fecha_asignacion=apoyo.fecha_inicio,
            fecha_fin_asignacion=apoyo.fecha_fin_prevista, es_principal=es_principal, frecuencia=frecuencia,
        )
        db.add(r)
        db.flush()
        if es_principal:
            principal_row = r
    if principal_row is not None:
        db.add(Recurso(responsable_apoyo_id=principal_row.id, tipo_recurso=recurso_tipo, descripcion_recurso=recurso_desc,
                       disponibilidad=DisponibilidadRecurso.DISPONIBLE))
    db.flush()


_CARGO = {Rol.DOCENTE: "Docente", Rol.BIENESTAR: "Profesional de Bienestar", Rol.COORDINADOR: "Coordinador de programa",
          Rol.ADMIN: "Personal administrativo"}


def generar_matriz(db: Session, plan: PlanMaarTea, actor: Usuario, *, request: Request | None = None,
                   sobrescribir: bool = False) -> list[Apoyo]:
    """Genera (o sincroniza) la matriz F7 desde el plan vigente. Regenerable e idempotente.

    * Un APOYO por ajuste y por estrategia DUA, con TIPO_APOYO, responsable principal y secundario, RECURSO y frecuencia.
    * Fechas vinculadas al calendario semestral activo (inicio/fin del semestre y cortes C1–C3). Sin calendario: 409.
    * Sin `sobrescribir` se conservan fechas, responsables y recursos editados a mano (solo se refrescan los textos).
    """
    if plan.estado not in ESTADOS_VIGENTES:
        raise Conflict(f"La matriz F7 se genera cuando el plan ya fue aprobado (estado actual: {plan.estado}).",
                       "PLAN_NO_APROBADO")
    cal = calendario_del_plan(db, plan)
    if cal is None:
        raise Conflict(
            f"No hay un calendario académico activo para el semestre {plan.semestre_academico}. Pida al administrador "
            "que lo configure (fechas de inicio, fin y cortes C1, C2 y C3) y genere la matriz de nuevo.",
            "CALENDARIO_NO_CONFIGURADO")
    db.flush()
    ajustes = list(db.scalars(select(AjusteRazonable).where(AjusteRazonable.plan_id == plan.id).order_by(AjusteRazonable.id)))
    estrategias = list(db.scalars(select(EstrategiaDua).where(EstrategiaDua.plan_id == plan.id).order_by(EstrategiaDua.id)))
    apoyos: list[Apoyo] = []
    vivos_a, vivos_e = set(), set()

    def _fechas(inicio: date | None, fin: date | None) -> tuple[date, date]:
        i = max(inicio or cal.fecha_inicio, cal.fecha_inicio)
        f = min(fin or cal.fecha_fin, cal.fecha_fin)
        if f < i:
            i, f = cal.fecha_inicio, cal.fecha_fin
        return i, f

    def _cargos(*ids: int | None) -> dict[int, str]:
        out = {}
        for uid in ids:
            if uid:
                u = db.get(Usuario, uid)
                if u is not None:
                    out[uid] = _CARGO.get(Rol(str(u.rol)), str(u.rol).title())
        return out

    for a in ajustes:
        vivos_a.add(a.id)
        cat = TipoAjuste(str(a.tipo_ajuste))
        barrera = db.get(BarreraIdentificada, a.barrera_asociada_id)
        intens = {Severidad.SEVERA: IntensidadApoyo.ALTA, Severidad.MODERADA: IntensidadApoyo.MEDIA,
                  Severidad.LEVE: IntensidadApoyo.BAJA}.get(Severidad(str(barrera.severidad)) if barrera else None,
                                                            IntensidadApoyo.MEDIA)
        inicio, fin = _fechas(a.fecha_inicio, a.fecha_fin_prevista)
        ap = _apoyo_existente(db, plan.id, ajuste_id=a.id)
        nuevo = ap is None
        textos = dict(nombre_apoyo=_recorta(a.nombre_ajuste, 200), descripcion_apoyo=a.descripcion_ajuste,
                      tipo_apoyo=_recorta(f"Ajuste razonable · {cats.categoria(cat).etiqueta}", 100),
                      objetivo=a.indicador_efectividad)
        if nuevo:
            ap = Apoyo(plan_id=plan.id, ajuste_id=a.id, calendario_id=cal.id, fecha_inicio=inicio, fecha_fin_prevista=fin,
                       continuidad_indefinida=False, intensidad=intens, estado=EstadoApoyo.PLANEADO, **textos)
            db.add(ap)
            db.flush()
            db.add(TipoApoyo(apoyo_id=ap.id, categoria_apoyo=_CATEGORIA_APOYO[cat]))
        else:
            for k, v in textos.items():
                setattr(ap, k, v)
            ap.calendario_id = cal.id
        if nuevo or sobrescribir:
            if not nuevo:
                ap.fecha_inicio, ap.fecha_fin_prevista, ap.intensidad = inicio, fin, intens
            p, s = _responsables_por_defecto(db, plan, a.responsable_id)
            _asignar_responsables(db, ap, p, s, _cargos(p, s), a.frecuencia, _TIPO_RECURSO_POR_CATEGORIA[cat],
                                  a.recurso or "Tiempo y disposición del responsable para aplicar el ajuste", actor.id)
        apoyos.append(ap)

    for e in estrategias:
        vivos_e.add(e.id)
        inicio, fin = _fechas(e.fecha_inicio_implementacion, None)
        ap = _apoyo_existente(db, plan.id, estrategia_id=e.id)
        nuevo = ap is None
        textos = dict(nombre_apoyo=_recorta(f"DUA: {e.nombre_estrategia}", 200), descripcion_apoyo=e.descripcion,
                      tipo_apoyo="Estrategia DUA (universal)", objetivo=e.alcance)
        if nuevo:
            ap = Apoyo(plan_id=plan.id, estrategia_id=e.id, calendario_id=cal.id, fecha_inicio=inicio,
                       fecha_fin_prevista=fin, continuidad_indefinida=False, intensidad=IntensidadApoyo.MEDIA,
                       estado=EstadoApoyo.PLANEADO, **textos)
            db.add(ap)
            db.flush()
            db.add(TipoApoyo(apoyo_id=ap.id, categoria_apoyo=CategoriaApoyo.ORIENTACION_ACADEMICA))
        else:
            for k, v in textos.items():
                setattr(ap, k, v)
            ap.calendario_id = cal.id
        if nuevo or sobrescribir:
            if not nuevo:
                ap.fecha_inicio, ap.fecha_fin_prevista = inicio, fin
            p, s = _responsables_por_defecto(db, plan, e.responsable_implementacion_id)
            _asignar_responsables(db, ap, p, s, _cargos(p, s), "Cada sesión de clase", TipoRecurso.MATERIAL,
                                  "Diseño de la clase con la estrategia DUA", actor.id)
        apoyos.append(ap)

    # apoyos de elementos que ya no están en el plan -> soft delete
    for ap in db.scalars(select(Apoyo).where(Apoyo.plan_id == plan.id)):
        huerfano = (ap.ajuste_id and ap.ajuste_id not in vivos_a) or (ap.estrategia_id and ap.estrategia_id not in vivos_e)
        if huerfano:
            ap.soft_delete(actor.id, "El ajuste o la estrategia ya no forma parte del plan")
    audit.log(db, actor, common.A_MATRIZ_GENERADA, "plan_maar_tea", plan.id,
              {"apoyos": len(apoyos), "sobrescribir": sobrescribir, "calendario_id": cal.id}, request=request,
              estudiante_id=plan.estudiante_id)
    db.flush()
    return apoyos


def tiene_matriz(db: Session, plan_id: int) -> bool:
    db.flush()
    return db.scalar(select(Apoyo.id).where(Apoyo.plan_id == plan_id).limit(1)) is not None


def _ref_responsable(db: Session, r: ResponsableApoyo | None) -> dict | None:
    if r is None:
        return None
    u = common.ref_usuario(db, r.usuario_responsable_id)
    return {"id": r.id, "usuario": u, "cargo": r.cargo_responsable, "frecuencia": r.frecuencia,
            "porcentaje_dedicacion": r.porcentaje_dedicacion, "fecha_asignacion": r.fecha_asignacion.isoformat()}


def matriz_de(db: Session, plan: PlanMaarTea, *, apoyo_ids: set[int] | None = None, ajuste_ids: set[int] | None = None,
              estrategia_ids: set[int] | None = None) -> dict:
    """Matriz F7 serializada. Los filtros restringen a los apoyos del docente (sin datos clínicos)."""
    db.flush()
    cal = calendario_del_plan(db, plan)
    out_apoyos = []
    for ap in db.scalars(select(Apoyo).where(Apoyo.plan_id == plan.id).order_by(Apoyo.id)):
        if apoyo_ids is not None and ap.id not in apoyo_ids:
            continue
        resp = list(db.scalars(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == ap.id)
                               .order_by(ResponsableApoyo.es_principal.desc(), ResponsableApoyo.id)))
        principal = next((r for r in resp if r.es_principal), None)
        secundario = next((r for r in resp if not r.es_principal), None)
        recurso = None
        if principal is not None:
            rec = db.scalar(select(Recurso).where(Recurso.responsable_apoyo_id == principal.id).order_by(Recurso.id))
            if rec is not None:
                recurso = {"id": rec.id, "tipo_recurso": str(rec.tipo_recurso), "descripcion_recurso": rec.descripcion_recurso,
                           "cantidad": rec.cantidad, "unidad_medida": rec.unidad_medida,
                           "disponibilidad": str(rec.disponibilidad)}
        tipo = db.scalar(select(TipoApoyo).where(TipoApoyo.apoyo_id == ap.id))
        cortes = [c for c in _cortes(cal) if ap.fecha_inicio.isoformat() <= c["fecha"] <= (ap.fecha_fin_prevista or date.max).isoformat()]
        impl = list(db.scalars(select(ImplementacionApoyo).where(
            ImplementacionApoyo.responsable_apoyo_id.in_([r.id for r in resp] or [-1]),
            ImplementacionApoyo.estado == EstadoImplementacion.EJECUTADA)))
        out_apoyos.append({
            "id": ap.id, "ajuste_id": ap.ajuste_id, "estrategia_id": ap.estrategia_id, "nombre_apoyo": ap.nombre_apoyo,
            "descripcion_apoyo": ap.descripcion_apoyo, "tipo_apoyo": ap.tipo_apoyo,
            "categoria_apoyo": str(tipo.categoria_apoyo) if tipo else None, "objetivo": ap.objetivo,
            "fecha_inicio": ap.fecha_inicio.isoformat(),
            "fecha_fin_prevista": ap.fecha_fin_prevista.isoformat() if ap.fecha_fin_prevista else None,
            "intensidad": str(ap.intensidad), "estado": str(ap.estado), "frecuencia": principal.frecuencia if principal else None,
            "responsable_principal": _ref_responsable(db, principal), "responsable_secundario": _ref_responsable(db, secundario),
            "recurso": recurso, "cortes": cortes, "implementaciones_ejecutadas": len(impl),
        })
    if ajuste_ids is not None or estrategia_ids is not None:
        out_apoyos = [a for a in out_apoyos if (a["ajuste_id"] in (ajuste_ids or set())) or (a["estrategia_id"] in (estrategia_ids or set()))]
    return {
        "plan_id": plan.id, "version": plan.version, "semestre_academico": plan.semestre_academico,
        "calendario": ({"id": cal.id, "semestre_academico": cal.semestre_academico, "fecha_inicio": cal.fecha_inicio.isoformat(),
                        "fecha_fin": cal.fecha_fin.isoformat(), "cortes": _cortes(cal)} if cal else None),
        "apoyos": out_apoyos,
        "tasa_implementacion": resumen_implementacion(db, plan.id),
    }


def actualizar_apoyo(db: Session, plan: PlanMaarTea, apoyo_id: int, actor: Usuario, datos: dict,
                     request: Request | None = None) -> Apoyo:
    """Edición manual de un apoyo de la matriz F7 (Bienestar / Coordinador). No altera el contenido firmado del plan."""
    ap = db.get(Apoyo, apoyo_id)
    if ap is None or ap.deleted_at is not None or ap.plan_id != plan.id:
        raise NotFound("No encontramos ese apoyo en la matriz del plan.", "APOYO_NO_ENCONTRADO")
    cal = calendario_del_plan(db, plan)
    campos = []
    for k in ("fecha_inicio", "fecha_fin_prevista", "intensidad", "estado", "objetivo", "continuidad_indefinida"):
        if k in datos and datos[k] != getattr(ap, k):
            setattr(ap, k, datos[k])
            campos.append(k)
    _check_fechas(ap.fecha_inicio, ap.fecha_fin_prevista)
    if cal is not None and ("fecha_inicio" in campos or "fecha_fin_prevista" in campos):
        if ap.fecha_inicio < cal.fecha_inicio or (ap.fecha_fin_prevista and ap.fecha_fin_prevista > cal.fecha_fin):
            raise Unprocessable(
                f"Las fechas del apoyo deben estar dentro del semestre ({cal.fecha_inicio} a {cal.fecha_fin}).",
                "FECHAS_FUERA_DE_CALENDARIO")
    resp = list(db.scalars(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == ap.id)))
    principal = next((r for r in resp if r.es_principal), None)
    secundario = next((r for r in resp if not r.es_principal), None)
    if "frecuencia" in datos:
        for r in resp:
            r.frecuencia = datos["frecuencia"]
        campos.append("frecuencia")
    for clave, es_principal, actual in (("responsable_principal_id", True, principal),
                                        ("responsable_secundario_id", False, secundario)):
        if clave not in datos:
            continue
        uid = datos[clave]
        if uid is not None:
            _check_responsable(db, uid)
        if actual is not None and actual.usuario_responsable_id == uid:
            continue
        recurso_previo = None
        if actual is not None:
            recurso_previo = db.scalar(select(Recurso).where(Recurso.responsable_apoyo_id == actual.id).order_by(Recurso.id))
        nuevo = None
        if uid is not None:
            u = db.get(Usuario, uid)
            nuevo = ResponsableApoyo(
                apoyo_id=ap.id, usuario_responsable_id=uid, cargo_responsable=_CARGO.get(Rol(str(u.rol)), str(u.rol).title()),
                porcentaje_dedicacion=100 if es_principal else 25, fecha_asignacion=ap.fecha_inicio,
                fecha_fin_asignacion=ap.fecha_fin_prevista, es_principal=es_principal,
                frecuencia=resp[0].frecuencia if resp else None)
            db.add(nuevo)
            db.flush()
        if recurso_previo is not None:
            if nuevo is not None and es_principal:
                recurso_previo.responsable_apoyo_id = nuevo.id  # el recurso pasa al nuevo principal
            else:
                recurso_previo.soft_delete(actor.id, "Cambio de responsable")
        if actual is not None:
            actual.soft_delete(actor.id, "Cambio de responsable")
        db.flush()
        campos.append(clave)
    if "recurso" in datos and datos["recurso"] is not None:
        principal = db.scalar(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == ap.id, ResponsableApoyo.es_principal.is_(True)))
        if principal is None:
            raise Conflict("Asigne primero un responsable principal para registrar el recurso.", "SIN_RESPONSABLE_PRINCIPAL")
        r = datos["recurso"]
        rec = db.scalar(select(Recurso).where(Recurso.responsable_apoyo_id == principal.id).order_by(Recurso.id))
        if rec is None:
            rec = Recurso(responsable_apoyo_id=principal.id, tipo_recurso=r.get("tipo_recurso", TipoRecurso.MATERIAL),
                          descripcion_recurso=r.get("descripcion_recurso") or "Recurso por definir")
            db.add(rec)
        for k in ("tipo_recurso", "descripcion_recurso", "cantidad", "unidad_medida", "disponibilidad"):
            if k in r and r[k] is not None:
                setattr(rec, k, r[k])
        campos.append("recurso")
    audit.log(db, actor, common.A_MATRIZ_EDITADA, "apoyo", ap.id, {"plan_id": plan.id, "campos": campos}, request=request,
              estudiante_id=plan.estudiante_id)
    db.flush()
    return ap


# ----------------------------------------------------------------------------- tasa de implementación (D6)
def resumen_implementacion(db: Session, plan_id: int, corte: str | None = None) -> dict:
    """Tasa de implementación del plan: apoyos de la matriz con al menos una implementación EJECUTADA (o estrategia DUA
    marcada como implementada) sobre el total de apoyos. Meta D6: >= 80 % al C2. `corte` (C1/C2/C3) limita a
    implementaciones hasta la fecha de ese corte en el calendario del plan."""
    db.flush()
    plan = db.get(PlanMaarTea, plan_id)
    hasta = None
    if corte and plan is not None:
        cal = calendario_del_plan(db, plan)
        if cal is not None:
            hasta = {"C1": cal.fecha_c1, "C2": cal.fecha_c2, "C3": cal.fecha_c3}.get(str(corte).upper())
    apoyos = list(db.scalars(select(Apoyo).where(Apoyo.plan_id == plan_id)))
    implementados = 0
    detalle = []
    for ap in apoyos:
        rids = list(db.scalars(select(ResponsableApoyo.id).where(ResponsableApoyo.apoyo_id == ap.id)))
        stmt = select(ImplementacionApoyo.id).where(
            ImplementacionApoyo.responsable_apoyo_id.in_(rids or [-1]),
            ImplementacionApoyo.estado == EstadoImplementacion.EJECUTADA)
        if hasta is not None:
            stmt = stmt.where(ImplementacionApoyo.fecha_implementacion <= hasta)
        n = len(list(db.scalars(stmt)))
        if n == 0 and ap.estrategia_id:
            e = db.get(EstrategiaDua, ap.estrategia_id)
            n = 1 if (e is not None and e.implementada) else 0
        implementados += 1 if n else 0
        detalle.append({"apoyo_id": ap.id, "nombre_apoyo": ap.nombre_apoyo, "implementaciones": n, "implementado": bool(n)})
    total = len(apoyos)
    tasa = round(100.0 * implementados / total, 1) if total else None
    return {"plan_id": plan_id, "corte": str(corte).upper() if corte else None,
            "hasta": hasta.isoformat() if hasta else None, "total_apoyos": total, "implementados": implementados,
            "tasa": tasa, "meta": META_TASA_IMPLEMENTACION,
            "cumple_meta": (tasa is not None and tasa >= META_TASA_IMPLEMENTACION), "detalle": detalle}


def tasa_implementacion(db: Session, plan_id: int, corte: str | None = None) -> float | None:
    """Porcentaje 0-100 de apoyos del plan implementados (None si el plan aún no tiene matriz F7). Meta D6: >= 80 al C2."""
    return resumen_implementacion(db, plan_id, corte)["tasa"]
