"""F10 (RF-34/35, HU-17): trayectoria, hitos, actualizacion del plan, notas de continuidad con aprobacion, plan siguiente."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import (
    Asignatura,
    DecisionPlan,
    EvaluacionPlan,
    Notificacion,
    PlanMaarTea,
    RespuestaAmbiente,
)
from app.models.enums import (
    ElementoAfectado,
    EstadoPlanEnum,
    TipoAmbientalAjuste,
    TipoDecision,
)
from app.services import f10 as svc_f10
from tests.c3_helpers import agregar_estrategia, plan_con_datos_clinicos, segundo_ajuste
from tests.factories import auth_headers, make_estudiante

API = "/api/v1"


def _u(w, est_id=None):
    return f"{API}/estudiantes/{est_id or w.estudiante.id}"


def _plan_con_f9(db, w):
    plan, a1 = plan_con_datos_clinicos(db, w)
    db.add(RespuestaAmbiente(ajuste_id=a1.id, tipo_ambiental_ajuste=TipoAmbientalAjuste.ESPACIO_TRANQUILO,
                             descripcion="Sala tranquila"))
    a2 = segundo_ajuste(db, plan, a1, asignatura_id=w.asignatura.id, nombre="Examen en sala aparte")
    a3 = segundo_ajuste(db, plan, a1, asignatura_id=w.asignatura.id, nombre="Tutoría semanal")
    est = agregar_estrategia(db, plan, w)
    ev = EvaluacionPlan(plan_id=plan.id, fecha_evaluacion=date.today(), evaluador_id=w.bienestar.id)
    db.add(ev)
    db.flush()
    for tipo, elem, eid, desc in (
        (TipoDecision.MODIFICAR, ElementoAfectado.AJUSTE, a2.id, "Examen en sala aparte con 30 minutos extra"),
        (TipoDecision.RETIRAR, ElementoAfectado.AJUSTE, a3.id, "Ya no se necesita"),
        (TipoDecision.CREAR_NUEVO, ElementoAfectado.PLAN_COMPLETO, None, "Anticipar guías de prácticas"),
    ):
        db.add(DecisionPlan(evaluacion_id=ev.id, tipo_decision=tipo, elemento_afectado=elem, elemento_id=eid,
                            descripcion_decision=desc, responsable_decision_id=w.bienestar.id))
    db.commit()
    return plan, a1, a2, a3, est


def _borrador(client, w, **body):
    r = client.post(f"{_u(w)}/f10/borrador", headers=auth_headers(w.bienestar), json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================================ trayectoria y hitos
def test_trayectoria_dos_semestres_nueve_dimensiones_y_resumen(client, db, world):
    w = world
    w.programa.duracion_semestres = 8
    w.programa.total_creditos = 160
    w.estudiante.semestre_actual = 2
    db.commit()
    hb = auth_headers(w.bienestar)
    r = client.post(f"{_u(w)}/trayectoria", headers=hb, json={
        "semestre_academico": "2026-I", "fecha_inicio_semestre": "2026-02-02", "asignaturas_inscritas": 5,
        "asignaturas_completadas": 5, "creditos_aprobados": 18, "promedio_academico": 4.1,
        "dimensiones": {"PERMANENCIA": {"continua_matriculado": True, "riesgo_desersion": "BAJO"},
                        "APRENDIZAJE": {"calificaciones_promedio": 4.1}}})
    assert r.status_code == 201, r.text
    t1 = r.json()
    assert set(t1["dimensiones"]) == {"ACCESO", "PARTICIPACION", "APRENDIZAJE", "BIENESTAR", "AUTONOMIA", "PERMANENCIA",
                                      "PROGRESION", "GRADUACION", "TRANSICION_PROFESIONAL"}
    assert t1["dimensiones"]["ACCESO"] is None and t1["dimensiones"]["PERMANENCIA"]["riesgo_desersion"] == "BAJO"
    assert client.post(f"{_u(w)}/trayectoria", headers=hb, json={
        "semestre_academico": "2026-I", "fecha_inicio_semestre": "2026-02-02"}).json()["code"] == "TRAYECTORIA_DUPLICADA"
    r = client.post(f"{_u(w)}/trayectoria", headers=hb, json={
        "semestre_academico": "2026-II", "fecha_inicio_semestre": "2026-08-03", "creditos_aprobados": 17})
    assert r.status_code == 201
    # edición por sección
    r = client.patch(f"{_u(w)}/trayectoria/2026-II/dimensiones/BIENESTAR", headers=hb,
                     json={"percepcion_bienestar": "ALTA", "siente_pertenencia": True})
    assert r.status_code == 200 and r.json()["dimensiones"]["BIENESTAR"]["percepcion_bienestar"] == "ALTA"
    r = client.patch(f"{_u(w)}/trayectoria/2026-II/dimensiones/PARTICIPACION", headers=hb, json={"asistencia_promedio": 140})
    assert r.status_code == 422
    r = client.patch(f"{_u(w)}/trayectoria/2026-II/dimensiones/GRADUACION", headers=hb, json={"campo_raro": 1})
    assert r.status_code == 422
    r = client.patch(f"{_u(w)}/trayectoria/2026-II/dimensiones/NOEXISTE", headers=hb, json={})
    assert r.status_code == 422
    r = client.patch(f"{_u(w)}/trayectoria/2026-II", headers=hb, json={
        "promedio_academico": 4.3, "dimensiones": {"TRANSICION_PROFESIONAL": {"sector_interes_profesional": "Cuidado crítico"}}})
    assert r.status_code == 200 and r.json()["promedio_academico"] == 4.3
    assert r.json()["dimensiones"]["TRANSICION_PROFESIONAL"]["sector_interes_profesional"] == "Cuidado crítico"
    # hitos
    h = client.post(f"{_u(w)}/hitos", headers=hb, json={"tipo_hito": "MATERIA_CLAVE", "fecha_hito": "2026-11-20",
                                                        "descripcion": "Aprobó Anatomía", "semestre_academico": "2026-II"})
    assert h.status_code == 201 and h.json()["semestre_academico"] == "2026-II"
    hid = h.json()["id"]
    assert client.patch(f"{_u(w)}/hitos/{hid}", headers=hb, json={"tipo_hito": "INICIO_PRACTICAS"}).json()["tipo_hito"] == "INICIO_PRACTICAS"
    # lectura por estudiante (mi) y coordinador; docente/familiar no
    lista = client.get(f"{API}/estudiantes/mi/trayectoria", headers=auth_headers(w.estudiante_user))
    assert lista.status_code == 200
    j = lista.json()
    assert [t["semestre_academico"] for t in j["trayectorias"]] == ["2026-I", "2026-II"]
    assert j["resumen"]["semestres_cursados"] == 2 and j["resumen"]["creditos_aprobados"] == 35
    assert j["resumen"]["proyeccion_graduacion"]["semestres_restantes"] == 6
    assert j["resumen"]["proyeccion_graduacion"]["semestre_estimado_graduacion"] == "2029-II"
    assert j["resumen"]["estado_permanencia"]["riesgo_desersion"] == "BAJO"
    assert client.get(f"{_u(w)}/trayectoria", headers=auth_headers(w.coordinador)).status_code == 200
    assert client.get(f"{_u(w)}/trayectoria", headers=auth_headers(w.coordinador_otro)).status_code == 403
    assert client.get(f"{_u(w)}/trayectoria", headers=auth_headers(w.docente)).status_code == 403
    assert client.get(f"{_u(w)}/trayectoria", headers=auth_headers(w.familiar)).status_code == 403
    assert client.get(f"{_u(w)}/trayectoria", headers=auth_headers(w.otro_estudiante_user)).status_code == 403
    # el estudiante y el coordinador no escriben
    for u in (w.estudiante_user, w.coordinador):
        assert client.patch(f"{_u(w)}/trayectoria/2026-II", headers=auth_headers(u), json={}).status_code == 403
        assert client.post(f"{_u(w)}/hitos", headers=auth_headers(u),
                           json={"tipo_hito": "OTRO", "fecha_hito": "2026-11-20"}).status_code == 403
    assert client.delete(f"{_u(w)}/hitos/{hid}", headers=hb).status_code == 200
    assert client.get(f"{_u(w)}/hitos", headers=hb).json() == []


def test_trayectoria_validaciones(client, db, world):
    hb = auth_headers(world.bienestar)
    r = client.post(f"{_u(world)}/trayectoria", headers=hb, json={"semestre_academico": "26-2"})
    assert r.status_code == 422
    r = client.post(f"{_u(world)}/trayectoria", headers=hb, json={"semestre_academico": "2026-II"})
    assert r.status_code == 422 and r.json()["code"] == "FECHA_INICIO_REQUERIDA"
    r = client.post(f"{_u(world)}/trayectoria", headers=hb, json={
        "semestre_academico": "2026-II", "fecha_inicio_semestre": "2026-08-03", "asignaturas_inscritas": 3,
        "asignaturas_completadas": 5})
    assert r.status_code == 422
    assert client.get(f"{_u(world)}/trayectoria/2030-I", headers=hb).status_code == 404


# ============================================================================ borrador F10
def test_borrador_desde_f9_y_edicion_de_actualizacion_del_plan(client, db, world):
    w = world
    plan, a1, a2, a3, est = _plan_con_f9(db, w)
    f = _borrador(client, w)
    assert f["semestre_origen"] == "2026-II" and f["semestre_destino"] == "2027-I" and f["estado"] == "BORRADOR"
    assert f["evaluacion_id"] and f["trayectoria"]["dimensiones"]["PERMANENCIA"]["continua_matriculado"] is True
    items = {(i["elemento"], i["elemento_id"]): i for i in f["actualizacion_plan"]["items"]}
    assert items[("AJUSTE", a1.id)]["tipo_decision"] == "MANTENER" and items[("AJUSTE", a1.id)]["origen_decision"] == "SIN_DECISION_F9"
    assert items[("AJUSTE", a2.id)]["tipo_decision"] == "MODIFICAR" and "30 minutos" in items[("AJUSTE", a2.id)]["descripcion_cambio"]
    assert items[("AJUSTE", a3.id)]["tipo_decision"] == "RETIRAR" and items[("AJUSTE", a3.id)]["origen_decision"] == "F9"
    assert items[("ESTRATEGIA", est.id)]["tipo_decision"] == "MANTENER"
    assert any(i["tipo_decision"] == "CREAR_NUEVO" and i["informativo"] for i in f["actualizacion_plan"]["items"])
    # duplicado
    r = client.post(f"{_u(w)}/f10/borrador", headers=auth_headers(w.bienestar), json={})
    assert r.status_code == 409 and r.json()["code"] == "F10_YA_EXISTE"
    # edición del componente 1
    hb = auth_headers(w.bienestar)
    url = f"{_u(w)}/f10/{f['id']}/actualizacion-plan"
    r = client.patch(url, headers=hb, json={"items": [{"elemento": "AJUSTE", "elemento_id": a1.id, "tipo_decision": "MODIFICAR"}]})
    assert r.status_code == 422  # modificar exige describir
    r = client.patch(url, headers=hb, json={"items": [{"elemento": "AJUSTE", "elemento_id": 99999, "tipo_decision": "MANTENER"}]})
    assert r.status_code == 422 and r.json()["code"] == "ELEMENTO_NO_PERTENECE_AL_PLAN"
    r = client.patch(url, headers=hb, json={
        "items": [{"elemento": "AJUSTE", "elemento_id": a3.id, "tipo_decision": "MANTENER", "justificacion": "Aún lo usa"}],
        "nuevos_propuestos": ["Apoyo en rotación clínica"], "observaciones": "Revisar con coordinación"})
    assert r.status_code == 200
    got = client.get(url, headers=auth_headers(w.coordinador)).json()
    assert got["nuevos_propuestos"] == ["Apoyo en rotación clínica"]
    assert {i["elemento_id"]: i["tipo_decision"] for i in got["items"] if i["elemento"] == "AJUSTE"}[a3.id] == "MANTENER"
    # solo Bienestar escribe
    for u in (w.estudiante_user, w.coordinador, w.docente):
        assert client.patch(url, headers=auth_headers(u), json={}).status_code == 403
    assert client.get(url, headers=auth_headers(w.docente)).status_code == 403


def test_borrador_sin_plan_ni_trayectoria_pide_semestre(client, db, world):
    r = client.post(f"{_u(world)}/f10/borrador", headers=auth_headers(world.bienestar), json={})
    assert r.status_code == 422 and r.json()["code"] == "SEMESTRE_ORIGEN_REQUERIDO"
    f = _borrador(client, world, semestre_origen="2026-I")
    assert f["semestre_destino"] == "2026-II" and f["plan_id"] is None


def test_f10_trayectoria_componente_y_necesidades(client, db, world):
    w = world
    w.programa.semestre_practicas = 3
    w.programa.duracion_semestres = 8
    w.estudiante.semestre_actual = 2
    db.add(Asignatura(programa_id=w.programa.id, codigo="ENF301", nombre="Práctica clínica I", semestre_plan=3, creditos=6,
                      es_practica=True, escenario_predominante="PRACTICA_CLINICA"))
    db.commit()
    f = _borrador(client, w, semestre_origen="2026-II")
    nec = f["necesidades_anticipadas"]
    assert nec and nec[0]["tipo"] == "PRACTICAS" and nec[0]["origen"] == "PROYECCION"
    proy = f["proyeccion"]["siguiente_semestre"]
    assert proy["nivel_semestre"] == 3 and proy["asignaturas"][0]["codigo"] == "ENF301" and proy["fuente"] == "ASIGNATURAS"
    hb = auth_headers(w.bienestar)
    url = f"{_u(w)}/f10/{f['id']}/trayectoria"
    r = client.patch(url, headers=hb, json={
        "trayectoria": {"creditos_aprobados": 16, "dimensiones": {"AUTONOMIA": {"gestiona_su_agenda": True}}},
        "necesidades_anticipadas": [{"tipo": "TRABAJO_GRADO", "semestre_estimado": "2028-II", "descripcion": "Asesor"}]})
    assert r.status_code == 200, r.text
    assert r.json()["trayectoria"]["dimensiones"]["AUTONOMIA"]["gestiona_su_agenda"] is True
    assert r.json()["necesidades_anticipadas"][0]["tipo"] == "TRABAJO_GRADO"
    assert client.get(url, headers=auth_headers(w.estudiante_user)).status_code == 200


def test_semestre_practicas_alerta_idempotente(db, world):
    w = world
    w.programa.semestre_practicas = 7
    w.estudiante.semestre_actual = 7
    w.otro_estudiante.programa_id = w.programa.id
    w.otro_estudiante.semestre_actual = 6
    db.commit()
    en = svc_f10.estudiantes_en_practicas(db, "2026-II")
    assert [e.estudiante_id for e in en] == [w.estudiante.id] and en[0].semestres_para_practicas == 0
    assert {e.estudiante_id for e in svc_f10.estudiantes_en_practicas(db, "2026-II", anticipacion=1)} == {
        w.estudiante.id, w.otro_estudiante.id}
    assert svc_f10.notificar_semestre_practicas(db, "2026-II") == 1
    db.commit()
    assert svc_f10.notificar_semestre_practicas(db, "2026-II") == 1  # no duplica notificaciones
    db.commit()
    notifs = db.scalars(select(Notificacion).where(Notificacion.tipo == "SEMESTRE_PRACTICAS")).all()
    assert len(notifs) == 0 or all(n.usuario_id == w.bienestar.id for n in notifs)  # canal solo correo según catálogo
    from app.models import EmailOutbox

    correos = db.scalars(select(EmailOutbox).where(EmailOutbox.evento == "SEMESTRE_PRACTICAS")).all()
    assert len(correos) == 1 and correos[0].usuario_id == w.bienestar.id


# ============================================================================ notas de continuidad (RF-35)
def test_nota_solo_visible_a_nuevos_actores_tras_aprobacion_del_estudiante(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    f = _borrador(client, w)
    base = f"{_u(w)}/f10/{f['id']}/notas"
    hb, he, hc = auth_headers(w.bienestar), auth_headers(w.estudiante_user), auth_headers(w.coordinador)
    r = client.post(base, headers=hb, json={"contenido": "Prefiere instrucciones escritas y avisos previos."})
    assert r.status_code == 201 and r.json()["estado"] == "BORRADOR"
    nid = r.json()["id"]
    # estado BORRADOR: ni coordinador ni otro bienestar nuevo
    otro_bien = _otro_bienestar(db)
    assert client.get(base, headers=hc).json() == []
    assert client.get(f"{_u(w)}/notas-continuidad?semestre_destino=2027-I", headers=hc).json() == []
    hn = auth_headers(otro_bien)  # profesional de Bienestar nuevo: tampoco ve lo no aprobado
    assert client.get(base, headers=hn).json() == []
    # enviar: pendiente de aprobación del estudiante; sigue invisible a coordinador
    r = client.post(f"{base}/{nid}/enviar", headers=hb)
    assert r.status_code == 200 and r.json()["estado"] == "PENDIENTE_APROBACION_ESTUDIANTE"
    assert client.get(base, headers=hc).json() == []
    notif = db.scalars(select(Notificacion).where(Notificacion.usuario_id == w.estudiante_user.id,
                                                   Notificacion.tipo == "NOTA_CONTINUIDAD_PENDIENTE")).all()
    assert len(notif) == 1
    # el estudiante la ve; coordinador no puede aprobar; bienestar no puede aprobar en su nombre
    assert any(n["contenido"].startswith("Prefiere") for n in client.get(base, headers=he).json())
    assert client.post(f"{base}/{nid}/aprobar", headers=hc).status_code == 403
    assert client.post(f"{base}/{nid}/aprobar", headers=hb).status_code == 403
    # aprobación explícita
    r = client.post(f"{base}/{nid}/aprobar", headers=he)
    assert r.status_code == 200 and r.json()["estado"] == "APROBADA" and r.json()["aprobada_por_estudiante"] is True
    assert r.json()["aprobada_at"]
    assert client.get(base, headers=hc).json()[0]["id"] == nid
    assert client.get(base, headers=hn).json()[0]["id"] == nid
    assert client.get(f"{_u(w)}/notas-continuidad?semestre_destino=2027-I", headers=hc).json()[0]["id"] == nid
    # fuera de alcance / matriz: docente, familiar, otro coordinador, admin, otro estudiante
    for u in (w.docente, w.familiar, w.coordinador_otro, w.admin, w.otro_estudiante_user):
        assert client.get(base, headers=auth_headers(u)).status_code == 403, u.rol
    # editar una nota aprobada la devuelve a BORRADOR (deja de ser visible)
    r = client.patch(f"{base}/{nid}", headers=hb, json={"contenido": "Texto nuevo de la nota"})
    assert r.status_code == 200 and r.json()["estado"] == "BORRADOR" and r.json()["advertencia"]
    assert client.get(base, headers=hc).json() == []
    assert client.post(f"{base}/{nid}/aprobar", headers=he).status_code == 409  # BORRADOR de Bienestar: primero enviar


def _otro_bienestar(db):
    from app.models.enums import Rol
    from tests.factories import make_user

    return make_user(db, Rol.BIENESTAR)


def test_estudiante_rechaza_y_bienestar_reenvia(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    f = _borrador(client, w)
    base = f"{_u(w)}/f10/{f['id']}/notas"
    hb, he = auth_headers(w.bienestar), auth_headers(w.estudiante_user)
    nid = client.post(base, headers=hb, json={"contenido": "Nota que el estudiante no quiere compartir"}).json()["id"]
    client.post(f"{base}/{nid}/enviar", headers=hb)
    assert client.post(f"{base}/{nid}/rechazar", headers=he, json={}).status_code == 422
    r = client.post(f"{base}/{nid}/rechazar", headers=he, json={"motivo": "Prefiero no compartir esto"})
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA" and r.json()["motivo_rechazo"]
    assert client.post(f"{base}/{nid}/aprobar", headers=he).status_code == 409
    r = client.post(f"{base}/{nid}/enviar", headers=hb)  # RECHAZADA puede reenviarse tras editar
    assert r.status_code == 200 and r.json()["estado"] == "PENDIENTE_APROBACION_ESTUDIANTE"
    assert client.get(base, headers=auth_headers(w.coordinador)).json() == []


def test_estudiante_redacta_su_nota_y_la_aprueba_explicitamente(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    f = _borrador(client, w)
    base = f"{API}/estudiantes/mi/f10/{f['id']}/notas"
    base_c = f"{_u(w)}/f10/{f['id']}/notas"  # el coordinador usa el id numérico
    he, hc = auth_headers(w.estudiante_user), auth_headers(w.coordinador)
    r = client.post(base, headers=he, json={"contenido": "Necesito saber el horario con una semana de anticipación",
                                            "destinatario": "COORDINADOR"})
    assert r.status_code == 201 and r.json()["estado"] == "BORRADOR" and r.json()["elaborada_por_rol"] == "ESTUDIANTE"
    nid = r.json()["id"]
    assert client.get(base_c, headers=hc).json() == []  # no aprobada aún
    assert client.post(f"{base}/{nid}/aprobar", headers=he).json()["estado"] == "APROBADA"
    assert client.get(base_c, headers=hc).json()[0]["id"] == nid
    # no puede editar notas ajenas
    nb = client.post(f"{_u(w)}/f10/{f['id']}/notas", headers=auth_headers(w.bienestar), json={"contenido": "Nota de Bienestar"}).json()
    assert client.patch(f"{base}/{nb['id']}", headers=he, json={"contenido": "cambio"}).status_code == 403
    # otro estudiante no puede escribir en este F10
    assert client.post(f"{_u(w)}/f10/{f['id']}/notas", headers=auth_headers(w.otro_estudiante_user),
                       json={"contenido": "intruso"}).status_code == 403
    # destinatario DOCENTE: no se expone a docentes (matriz) ni a coordinador
    nd = client.post(base, headers=he, json={"contenido": "Para el docente nuevo", "destinatario": "DOCENTE"}).json()
    client.post(f"{base}/{nd['id']}/aprobar", headers=he)
    assert nd["id"] not in [n["id"] for n in client.get(base_c, headers=hc).json()]
    assert client.get(base_c, headers=auth_headers(w.docente)).status_code == 403


# ============================================================================ aprobación y plan siguiente
def test_aprobacion_doble_crea_plan_siguiente_y_alimenta_f3(client, db, world):
    w = world
    plan, a1, a2, a3, est = _plan_con_f9(db, w)
    f = _borrador(client, w)
    hb, he = auth_headers(w.bienestar), auth_headers(w.estudiante_user)
    assert svc_f10.contexto_para_f3(db, w.estudiante.id, "2027-I") is None  # aún no aprobado
    r = client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=hb, json={})
    assert r.status_code == 200 and r.json()["estado"] == "PENDIENTE_APROBACION" and r.json()["aprobacion_bienestar"]["aprobado_at"]
    assert r.json()["plan_siguiente"] is None
    assert client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=hb).json()["code"] == "F10_YA_APROBADO_POR_USTED"
    assert db.scalars(select(Notificacion).where(Notificacion.tipo == "F10_PENDIENTE_APROBACION")).all()
    # coordinador y docente no aprueban
    for u in (w.coordinador, w.docente, w.familiar):
        assert client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=auth_headers(u)).status_code == 403
    assert svc_f10.contexto_para_f3(db, w.estudiante.id, "2027-I") is None  # falta el estudiante
    r = client.post(f"{API}/estudiantes/mi/f10/{f['id']}/aprobar", headers=he, json={"comentario": "De acuerdo"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["estado"] == "APROBADO" and j["aprobacion_estudiante"]["aprobado_at"] and j["aprobado_at"]
    ps = j["plan_siguiente"]
    assert ps["creado"] is True and ps["ajustes_copiados"] == 2 and ps["estrategias_copiadas"] == 1 and ps["retirados"] == 1
    db.expire_all()
    nuevo = db.get(PlanMaarTea, ps["plan_id"])
    assert nuevo.estado == EstadoPlanEnum.BORRADOR and nuevo.semestre_academico == "2027-I" and nuevo.estudiante_id == w.estudiante.id
    nombres = {a.nombre_ajuste: a for a in nuevo.ajustes}
    assert set(nombres) == {"Ubicación cerca de la puerta", "Examen en sala aparte"}  # el retirado no pasa
    assert nombres["Examen en sala aparte"].descripcion_ajuste.endswith("30 minutos extra")
    assert str(nombres["Examen en sala aparte"].estado) == "PROPUESTO"
    assert len(nombres["Ubicación cerca de la puerta"].resp_ambiente) == 1  # copia las respuestas por categoría
    assert len(nuevo.estrategias_dua) == 1 and str(nuevo.estrategias_dua[0].estado_implementacion) == "PLANEADA"
    # plan origen intacto
    assert db.get(PlanMaarTea, plan.id).estado == EstadoPlanEnum.IMPLEMENTACION
    # F10 inmutable
    r = client.patch(f"{_u(w)}/f10/{f['id']}/actualizacion-plan", headers=hb, json={"observaciones": "x"})
    assert r.status_code == 409 and r.json()["code"] == "F10_APROBADO_INMUTABLE"
    assert client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=hb).json()["code"] == "F10_YA_APROBADO"
    # contexto para el F3 del siguiente semestre
    ctx = svc_f10.contexto_para_f3(db, w.estudiante.id, "2027-I")
    assert ctx["f10_id"] == f["id"] and ctx["plan_siguiente_id"] == nuevo.id
    assert ctx["decisiones_plan"]["RETIRAR"] == ["Tutoría semanal"] and "Examen en sala aparte" in ctx["decisiones_plan"]["MODIFICAR"]
    assert ctx["escenarios_sugeridos"][:2] == ["AULA", "CAMPUS"]
    assert svc_f10.contexto_para_f3(db, w.estudiante.id, "2027-II") is None
    assert "CENTINELA" not in str(ctx)  # nunca texto de notas ni datos clínicos
    # hito de cambio de semestre registrado
    hitos = client.get(f"{_u(w)}/hitos", headers=hb).json()
    assert any(h["tipo_hito"] == "CAMBIO_SEMESTRE" for h in hitos)


def test_cambiar_el_f10_tras_una_aprobacion_la_invalida(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    f = _borrador(client, w)
    hb = auth_headers(w.bienestar)
    client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=hb)
    r = client.patch(f"{_u(w)}/f10/{f['id']}/actualizacion-plan", headers=hb, json={"observaciones": "Cambio posterior"})
    assert r.status_code == 200 and r.json()["advertencias"]
    got = client.get(f"{_u(w)}/f10/{f['id']}", headers=hb).json()
    assert got["estado"] == "BORRADOR" and got["aprobacion_bienestar"]["aprobado_at"] is None


def test_no_duplica_plan_si_ya_existe_para_el_siguiente_semestre(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    existente = PlanMaarTea(estudiante_id=w.estudiante.id, fecha_elaboracion=date.today(), semestre_academico="2027-I",
                            vigencia_inicio=date.today(), estado=EstadoPlanEnum.BORRADOR)
    db.add(existente)
    db.commit()
    f = _borrador(client, w, semestre_origen="2026-II")
    client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=auth_headers(w.bienestar))
    r = client.post(f"{_u(w)}/f10/{f['id']}/aprobar", headers=auth_headers(w.estudiante_user))
    assert r.status_code == 200 and r.json()["plan_siguiente"]["creado"] is False
    assert r.json()["plan_siguiente_id"] == existente.id


def test_rbac_f10(client, db, world):
    w = world
    plan_con_datos_clinicos(db, w)
    f = _borrador(client, w)
    url = f"{_u(w)}/f10/{f['id']}"
    for u in (w.bienestar, w.coordinador, w.estudiante_user):
        assert client.get(url, headers=auth_headers(u)).status_code == 200
    for u in (w.docente, w.familiar, w.coordinador_otro, w.otro_estudiante_user, w.admin):
        assert client.get(url, headers=auth_headers(u)).status_code == 403, u.rol
        assert client.get(f"{_u(w)}/f10", headers=auth_headers(u)).status_code == 403
    for u in (w.estudiante_user, w.coordinador, w.docente, w.familiar):
        assert client.post(f"{_u(w)}/f10/borrador", headers=auth_headers(u), json={}).status_code == 403
    assert client.get(f"{API}/estudiantes/mi/f10", headers=auth_headers(w.estudiante_user)).status_code == 200
    assert client.get(f"{_u(w)}/f10/9999", headers=auth_headers(w.bienestar)).json()["code"] == "F10_NO_ENCONTRADO"
    # el coordinador solo ve notas aprobadas dentro del F10 completo
    client.post(f"{url}/notas", headers=auth_headers(w.bienestar), json={"contenido": "Borrador interno"})
    assert client.get(url, headers=auth_headers(w.coordinador)).json()["notas"] == []
    assert len(client.get(url, headers=auth_headers(w.estudiante_user)).json()["notas"]) == 2  # la del seed de pruebas + la nueva


def test_f10_sin_consentimiento_f0_bloquea(client, db, world):
    sin, est = make_estudiante(db, world.programa, consent=False)
    r = client.get(f"{API}/estudiantes/{est.id}/f10", headers=auth_headers(world.bienestar))
    assert r.status_code == 403 and r.json()["code"] == "ESTUDIANTE_SIN_CONSENTIMIENTO"
    r = client.get(f"{API}/estudiantes/mi/f10", headers=auth_headers(sin))
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
