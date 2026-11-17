"""Slice C2: seguimiento F8 por cortes, semaforo (RF-29, RF-39), percepcion (HU-21) y RBAC."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    BarreraIdentificada,
    EmailOutbox,
    LogAuditoria,
    Notificacion,
    RegistroSeguimientoAjuste,
)
from app.models.enums import EstadoPlanEnum
from app.services import seguimiento as svc
from tests.factories import authorize_familiar, make_estudiante, make_user
from tests.test_slice_c2_common import Api, hoy, make_calendario, make_plan_impl

BASE = "/planes/{pid}/seguimiento"


@pytest.fixture()
def ctx(client, db, world):
    cal = make_calendario(db)
    plan, ajustes = make_plan_impl(db, world)
    return Api(client), world, plan, ajustes, cal


def _abrir(api, w, plan, corte="C1"):
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/{corte}")
    assert r.status_code in (200, 201), r.text
    return r


def _sem(api, w, plan, ajuste, semaforo, corte="C1", **extra):
    body = {"semaforo": semaforo, "implementado": True, "resultado_observado": "Observación de prueba.", **extra}
    return api.put(w.bienestar, f"/planes/{plan.id}/seguimiento/{corte}/ajustes/{ajuste.id}", body)


# ----------------------------------------------------------------------------- calendario y cortes
def test_sin_calendario_409_claro(client, db, world):
    plan, _ = make_plan_impl(db, world)
    r = Api(client).get(world.bienestar, f"/planes/{plan.id}/seguimiento")
    assert r.status_code == 409 and r.json()["code"] == "CALENDARIO_NO_CONFIGURADO"
    r = Api(client).post(world.bienestar, f"/planes/{plan.id}/seguimiento/C1")
    assert r.status_code == 409 and r.json()["code"] == "CALENDARIO_NO_CONFIGURADO"


def test_cortes_del_calendario_y_estados(ctx):
    api, w, plan, ajustes, cal = ctx
    r = api.get(w.bienestar, f"/planes/{plan.id}/seguimiento")
    assert r.status_code == 200
    cortes = r.json()["cortes"]
    assert [c["corte"] for c in cortes] == ["C1", "C2", "C3"]
    assert [c["estado"] for c in cortes] == ["FUTURO"] * 3
    assert cortes[0]["fecha_corte"] == cal.fecha_c1.isoformat()
    assert cortes[0]["vencido"] is True and cortes[0]["puede_abrir"] is True
    _abrir(api, w, plan)
    cortes = api.get(w.bienestar, f"/planes/{plan.id}/seguimiento").json()["cortes"]
    assert cortes[0]["estado"] == "ABIERTO"
    assert cortes[1]["puede_abrir"] is False and cortes[1]["bloqueo"]["code"] == "CORTE_ANTERIOR_ABIERTO"


def test_abrir_corte_crea_e_idempotente_y_mueve_plan_a_seguimiento(ctx, db):
    api, w, plan, _, _ = ctx
    assert _abrir(api, w, plan).status_code == 201
    assert _abrir(api, w, plan).status_code == 200
    db.refresh(plan)
    assert plan.estado == EstadoPlanEnum.SEGUIMIENTO


def test_abrir_corte_solo_planes_en_implementacion_o_seguimiento(client, db, world):
    make_calendario(db)
    plan, _ = make_plan_impl(db, world, estado=EstadoPlanEnum.APROBADO)
    r = Api(client).post(world.bienestar, f"/planes/{plan.id}/seguimiento/C1")
    assert r.status_code == 409 and r.json()["code"] == "PLAN_NO_EN_SEGUIMIENTO"


def test_corte_invalido_422(ctx):
    api, w, plan, _, _ = ctx
    assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C9").status_code == 422


# ----------------------------------------------------------------------------- reglas del semaforo
def _destinatarios(db, tipo):
    return {n.usuario_id for n in db.scalars(select(Notificacion).where(Notificacion.tipo == tipo))}


def test_rojo_notifica_exactamente_a_los_4_actores_push_y_correo(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    r = _sem(api, w, plan, ajustes[0], "ROJO")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["semaforo"]["notificados"]) == ["BIENESTAR", "COORDINADOR", "DOCENTE", "ESTUDIANTE"]
    esperados = {w.bienestar.id, w.coordinador.id, w.docente.id, w.estudiante_user.id}
    assert _destinatarios(db, "AJUSTE_SEMAFORO_ROJO") == esperados
    correos = {e.usuario_id for e in db.scalars(select(EmailOutbox).where(EmailOutbox.evento == "AJUSTE_SEMAFORO_ROJO"))}
    assert correos == esperados  # push + correo inmediato (RF-39)
    # no se notifica a quien no es parte (otro coordinador, otro docente, otro estudiante, familiar, admin)
    ajenos = {w.coordinador_otro.id, w.docente_otro.id, w.otro_estudiante_user.id, w.familiar.id, w.admin.id}
    assert not (_destinatarios(db, "AJUSTE_SEMAFORO_ROJO") & ajenos)


def test_rojo_dedupe_no_duplica_si_se_reenvia(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "ROJO")
    r = _sem(api, w, plan, ajustes[0], "ROJO")  # mismo semaforo otra vez
    assert r.json()["semaforo"]["cambio"] is False
    assert db.query(Notificacion).filter_by(tipo="AJUSTE_SEMAFORO_ROJO").count() == 4
    # ROJO -> AMARILLO -> ROJO sobre el mismo registro: dedupe por (registro, usuario), no hay segunda tanda
    _sem(api, w, plan, ajustes[0], "AMARILLO")
    _sem(api, w, plan, ajustes[0], "ROJO")
    assert db.query(Notificacion).filter_by(tipo="AJUSTE_SEMAFORO_ROJO").count() == 4


def test_cada_cambio_de_semaforo_se_audita_de_a_quien(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "AMARILLO")
    _sem(api, w, plan, ajustes[0], "VERDE")
    logs = list(db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "CAMBIO_SEMAFORO").order_by(LogAuditoria.id)))
    assert [(x.detalle["de"], x.detalle["a"]) for x in logs] == [(None, "AMARILLO"), ("AMARILLO", "VERDE")]
    assert all(x.actor_id == w.bienestar.id and x.estudiante_id == w.estudiante.id for x in logs)


def test_rojo_bloquea_siguiente_corte_hasta_registrar_redisenio(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "ROJO")
    assert _sem(api, w, plan, ajustes[1], "VERDE").status_code == 200
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/cerrar")
    assert r.status_code == 200, r.text
    assert r.json()["rojos_sin_rediseno"] == [ajustes[0].id]
    reg = api.get(w.bienestar, f"/planes/{plan.id}/seguimiento/C1").json()["ajustes"][0]["registro"]
    assert reg["estado_seguimiento"] == "REQUIERE_REDISENO"
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C2")
    assert r.status_code == 409 and r.json()["code"] == "REDISENO_PENDIENTE"
    # el rediseño solo aplica a ajustes en ROJO
    assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[1].id}/rediseno",
                    {"decision": "MODIFICAR", "descripcion": "No corresponde a este ajuste."}).status_code == 409
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}/rediseno",
                 {"decision": "MODIFICAR", "descripcion": "Cambiar la ubicación a la fila lateral.", "concertado_con_estudiante": True})
    assert r.status_code == 200 and r.json()["registro"]["estado_seguimiento"] == "REDISENO_REGISTRADO"
    assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C2").status_code == 201


def test_amarillo_crea_tarea_concertacion_con_fecha_limite_siguiente_corte(ctx, db):
    api, w, plan, ajustes, cal = ctx
    _abrir(api, w, plan)
    r = _sem(api, w, plan, ajustes[0], "AMARILLO")
    t = r.json()["semaforo"]["tarea_concertacion"]
    assert t["estado"] == "ABIERTA" and t["fecha_limite"] == cal.fecha_c2.isoformat()
    assert _destinatarios(db, "TAREA_CONCERTACION") == {w.bienestar.id, w.estudiante_user.id}
    # el amarillo no dispara la alerta roja
    assert db.query(Notificacion).filter_by(tipo="AJUSTE_SEMAFORO_ROJO").count() == 0
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}/concertacion",
                 {"acuerdo": "Se cambia el horario de la tutoría."})
    assert r.status_code == 200 and r.json()["registro"]["estado_seguimiento"] == "CONCERTACION_RESUELTA"
    assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}/concertacion",
                    {"acuerdo": "Otra vez lo mismo."}).status_code == 409


def test_verde_queda_como_efectivo(ctx):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    r = _sem(api, w, plan, ajustes[0], "VERDE")
    assert r.json()["registro"]["estado_seguimiento"] == "EFECTIVO"


def test_rojo_o_amarillo_exigen_resultado_observado(ctx):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    r = api.put(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}", {"semaforo": "ROJO"})
    assert r.status_code == 422 and r.json()["code"] == "RESULTADO_OBSERVADO_REQUERIDO"


def test_cerrar_corte_exige_semaforo_en_todos_los_ajustes_y_actualiza_caches(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "VERDE")
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/cerrar")
    assert r.status_code == 409 and r.json()["code"] == "AJUSTES_SIN_SEMAFORO"
    _sem(api, w, plan, ajustes[1], "AMARILLO")
    r = api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/cerrar")
    assert r.status_code == 200 and r.json()["semaforo_agregado"] == "AMARILLO"
    db.refresh(plan)
    assert str(plan.semaforo_actual) == "AMARILLO"
    assert _sem(api, w, plan, ajustes[0], "ROJO").status_code == 409  # corte cerrado


# ----------------------------------------------------------------------------- percepcion (HU-21)
def test_percepcion_solo_la_escribe_el_estudiante(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    url = f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}"
    # el estudiante escribe antes de que Bienestar valore (fila sin semaforo)
    r = api.put(w.estudiante_user, url + "/percepcion", {"percepcion": "NEGATIVA", "comentario": "Me incomoda."})
    assert r.status_code == 200 and r.json()["registro"]["semaforo"] is None
    # Bienestar NO puede escribirla: el esquema la rechaza y el endpoint de percepcion es solo del estudiante
    r = api.put(w.bienestar, url, {"semaforo": "VERDE", "percepcion_estudiante": "POSITIVA"})
    assert r.status_code == 422
    r = api.put(w.bienestar, url + "/percepcion", {"percepcion": "POSITIVA"})
    assert r.status_code == 403
    r = api.put(w.bienestar, url, {"semaforo": "VERDE", "implementado": True})
    assert r.status_code == 200
    assert "negativa" in " ".join(r.json()["semaforo"]["advertencias"]).lower()
    reg = db.scalar(select(RegistroSeguimientoAjuste).where(RegistroSeguimientoAjuste.ajuste_id == ajustes[0].id))
    db.refresh(reg)
    assert str(reg.percepcion_estudiante) == "NEGATIVA" and reg.comentario_estudiante == "Me incomoda."
    # ni docente, ni coordinador, ni otro estudiante, ni familiar
    for u in (w.docente, w.coordinador, w.otro_estudiante_user, w.familiar):
        assert api.put(u, url + "/percepcion", {"percepcion": "POSITIVA"}).status_code == 403
    # el propio estudiante puede corregirla mientras el corte esté abierto
    assert api.put(w.estudiante_user, url + "/percepcion", {"percepcion": "PARCIAL"}).status_code == 200


def test_percepcion_requiere_corte_abierto(ctx):
    api, w, plan, ajustes, _ = ctx
    r = api.put(w.estudiante_user, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}/percepcion", {"percepcion": "POSITIVA"})
    assert r.status_code == 404 and r.json()["code"] == "CORTE_NO_ABIERTO"


# ----------------------------------------------------------------------------- RBAC §12.1
def test_matriz_de_acceso_seguimiento(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "VERDE")
    url = f"/planes/{plan.id}/seguimiento/C1"
    # lectura: Bienestar, Coordinador del programa, Estudiante propio
    for u in (w.bienestar, w.coordinador, w.estudiante_user):
        assert api.get(u, url).status_code == 200
    # sin acceso
    for u in (w.coordinador_otro, w.otro_estudiante_user, w.admin, w.familiar):
        assert api.get(u, url).status_code == 403, u.rol
    # escritura: solo Bienestar
    for u in (w.coordinador, w.docente, w.estudiante_user, w.familiar):
        assert api.put(u, f"{url}/ajustes/{ajustes[0].id}", {"semaforo": "ROJO", "resultado_observado": "x" * 5}).status_code == 403
        assert api.post(u, f"/planes/{plan.id}/seguimiento/C2").status_code == 403
    # familiar: solo con autorizacion de alcance SEGUIMIENTO
    authorize_familiar(db, w.estudiante, w.familiar, ["SEGUIMIENTO"])
    assert api.get(w.familiar, url).status_code == 200


def test_docente_ve_solo_sus_ajustes_sin_percepcion_ni_datos_clinicos(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "VERDE")
    _sem(api, w, plan, ajustes[1], "VERDE")
    api.put(w.estudiante_user, f"/planes/{plan.id}/seguimiento/C1/ajustes/{ajustes[0].id}/percepcion",
            {"percepcion": "POSITIVA", "comentario": "Privado"})
    r = api.get(w.docente, f"/planes/{plan.id}/seguimiento/C1")
    assert r.status_code == 200
    j = r.json()
    assert [a["ajuste_id"] for a in j["ajustes"]] == [ajustes[0].id]  # solo el suyo
    assert "descripcion_situacion_actual" not in j and "registros" not in j
    assert "percepcion_estudiante" not in j["ajustes"][0]["registro"] and "comentario_estudiante" not in j["ajustes"][0]["registro"]
    sd = api.get(w.docente, f"/planes/{plan.id}/semaforo").json()
    assert [a["ajuste_id"] for a in sd["ajustes"]] == [ajustes[0].id] and "indicadores" not in sd
    # el docente de otra asignatura no ve el plan
    assert api.get(w.docente_otro, f"/planes/{plan.id}/semaforo").status_code == 403


# ----------------------------------------------------------------------------- evidencias, barreras, dashboard
def test_registros_y_evidencias_con_resultado_por_dimension(ctx):
    api, w, plan, _, _ = ctx
    _abrir(api, w, plan)
    base = f"/planes/{plan.id}/seguimiento/C1"
    r = api.post(w.bienestar, base + "/registros", {"tipo_registro": "ENTREVISTA", "descripcion_metodologia": "Conversación"})
    assert r.status_code == 201
    r = api.post(w.bienestar, base + "/evidencias", {
        "tipo_evidencia": "ACADEMICA", "descripcion_evidencia": "Notas del primer corte", "dato_cuantitativo": 4.2,
        "resultados": [{"dimension_resultado": "APRENDIZAJE", "indicador_especifico": "Promedio", "porcentaje_cumplimiento": 84}]})
    assert r.status_code == 201 and r.json()["resultados"][0]["dimension_resultado"] == "APRENDIZAJE"
    j = api.get(w.bienestar, base).json()
    assert len(j["registros"]) == 1 and len(j["evidencias"]) == 1
    assert api.post(w.bienestar, base + "/evidencias", {"tipo_evidencia": "ACADEMICA", "descripcion_evidencia": "x" * 4,
                    "resultados": [{"dimension_resultado": "OTRA", "indicador_especifico": "abc"}]}).status_code == 422
    assert api.delete(w.bienestar, base + f"/evidencias/{j['evidencias'][0]['id']}").status_code == 200
    assert api.get(w.bienestar, base).json()["evidencias"] == []


def test_barrera_emergente_crea_barrera_y_propone_ajuste(ctx, db):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    base = f"/planes/{plan.id}/seguimiento/C1/barreras-emergentes"
    antes = db.query(BarreraIdentificada).count()
    r = api.post(w.bienestar, base, {
        "tipo_barrera": "SENSORIAL", "descripcion_barrera": "Nuevo laboratorio con extractores muy ruidosos",
        "ajuste_id": ajustes[0].id,
        "propuesta_ajuste": {"nombre_ajuste": "Protectores auditivos", "descripcion_ajuste": "Uso permitido en laboratorio",
                             "justificacion": "Reduce el ruido", "tipo_ajuste": "AMBIENTE"}})
    assert r.status_code == 201, r.text
    assert db.query(BarreraIdentificada).count() == antes + 1
    assert r.json()["propuesta_ajuste"]["nombre_ajuste"] == "Protectores auditivos"
    j = api.get(w.bienestar, f"/planes/{plan.id}/seguimiento/C1").json()
    assert len(j["barreras_emergentes"]) == 1 and "Protectores" in j["ajustes_recomendados"]
    # barrera social: propuesta institucional obligatoria (RF-19)
    r = api.post(w.bienestar, base, {"tipo_barrera": "SOCIAL", "descripcion_barrera": "Aislamiento en trabajo grupal"})
    assert r.status_code == 422 and r.json()["code"] == "PROPUESTA_INSTITUCIONAL_REQUERIDA"


def test_dashboard_semaforo_matriz_tendencia_y_porcentaje_verde(ctx):
    api, w, plan, ajustes, _ = ctx
    _abrir(api, w, plan)
    _sem(api, w, plan, ajustes[0], "AMARILLO")
    _sem(api, w, plan, ajustes[1], "VERDE", implementado=False)
    api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/cerrar")
    _abrir(api, w, plan, "C2")
    _sem(api, w, plan, ajustes[0], "VERDE", corte="C2")
    _sem(api, w, plan, ajustes[1], "ROJO", corte="C2", implementado=False)
    j = api.get(w.estudiante_user, f"/planes/{plan.id}/semaforo").json()
    por_id = {a["ajuste_id"]: a for a in j["ajustes"]}
    assert por_id[ajustes[0].id]["tendencia"] == "MEJORA" and por_id[ajustes[1].id]["tendencia"] == "EMPEORA"
    assert j["resumen"]["por_corte"]["C1"]["porcentaje_verde"] == 50.0
    assert j["resumen"]["por_corte"]["C2"]["porcentaje_verde"] == 50.0 and j["resumen"]["semaforo_agregado"] == "ROJO"
    assert j["resumen"]["requieren_rediseno"] == [ajustes[1].id]
    assert j["tendencia"]["series"][0]["valores"] == [1, 0, None]
    assert j["indicadores"]["D6"]["valor"] == 50.0 and j["indicadores"]["D6"]["cumple"] is False


# ----------------------------------------------------------------------------- API para run_daily_jobs
def test_cortes_proximos_y_pendientes_de_corte(ctx, db):
    api, w, plan, ajustes, cal = ctx
    h = hoy()
    assert [c["corte"] for c in svc.cortes_proximos(db, cal.fecha_c2 - __import__("datetime").timedelta(days=7))] == ["C2"]
    assert svc.cortes_proximos(db, h, dias=(7,))[0]["corte"] == "C2" and svc.cortes_proximos(db, h, dias=(3,)) == []
    p = svc.pendientes_de_corte(db, "C1")
    assert len(p) == 1 and p[0]["plan_id"] == plan.id and p[0]["estado_corte"] == "SIN_ABRIR"
    assert p[0]["bienestar_usuario_id"] == w.bienestar.id and p[0]["docente_usuario_ids"] == [w.docente.id]
    _abrir(api, w, plan)
    assert svc.pendientes_de_corte(db, "C1")[0]["estado_corte"] == "ABIERTO"
    _sem(api, w, plan, ajustes[0], "VERDE")
    _sem(api, w, plan, ajustes[1], "VERDE")
    api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/cerrar")
    assert svc.pendientes_de_corte(db, "C1") == []
    assert isinstance(date.today(), date) and make_user and make_estudiante  # (importados para claridad)
