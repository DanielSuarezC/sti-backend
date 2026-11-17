"""Slice C2: evaluacion F9 (RF-32/33, HU-16), indicadores D6/D8, cierre y alimentacion del CBR."""

from __future__ import annotations

import json

import pytest

from app.models import CasoCbr, DecisionPlan
from app.models.enums import EstadoPlanEnum
from tests.test_slice_c2_common import Api, make_calendario, make_estado_plan, make_estrategia_para, make_plan_impl

DIMS = ["ACCESO", "PARTICIPACION", "APRENDIZAJE", "BIENESTAR", "AUTONOMIA", "PERMANENCIA", "PROGRESION", "GRADUACION", "TRANSICION"]


@pytest.fixture()
def ctx(client, db, world):
    make_calendario(db)
    make_estado_plan(db)
    plan, ajustes = make_plan_impl(db, world)
    make_estrategia_para(db, plan, ajustes[0])
    return Api(client), world, plan, ajustes


def _corte(api, w, plan, corte, semaforos, *, cerrar=True):
    assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/{corte}").status_code in (200, 201)
    for aj, s in semaforos:
        r = api.put(w.bienestar, f"/planes/{plan.id}/seguimiento/{corte}/ajustes/{aj.id}",
                    {"semaforo": s, "implementado": True, "resultado_observado": "Observado en clase."})
        assert r.status_code == 200, r.text
    if cerrar:
        assert api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/{corte}/cerrar").status_code == 200


def _tres_cortes(api, w, plan, a):
    _corte(api, w, plan, "C1", [(a[0], "VERDE"), (a[1], "ROJO")])
    api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C1/ajustes/{a[1].id}/rediseno",
             {"decision": "MODIFICAR", "descripcion": "Cambiar el formato de las instrucciones."})
    _corte(api, w, plan, "C2", [(a[0], "VERDE"), (a[1], "AMARILLO")])
    _corte(api, w, plan, "C3", [(a[0], "VERDE"), (a[1], "ROJO")])
    api.post(w.bienestar, f"/planes/{plan.id}/seguimiento/C3/ajustes/{a[1].id}/rediseno",
             {"decision": "RETIRAR", "descripcion": "Se retira: no funcionó en el semestre."})


def _valoracion():
    return {d: {"nivel": "ALTA" if i % 2 else "MEDIA", "comentario": "ok"} for i, d in enumerate(DIMS)}


def test_borrador_requiere_seguimiento_y_es_unico(ctx):
    api, w, plan, _ = ctx
    r = api.post(w.bienestar, f"/planes/{plan.id}/evaluacion")
    assert r.status_code == 409 and r.json()["code"] == "SIN_SEGUIMIENTO"


def test_borrador_consolida_cortes_con_sintesis_e_indicadores(ctx):
    api, w, plan, a = ctx
    _tres_cortes(api, w, plan, a)
    r = api.post(w.bienestar, f"/planes/{plan.id}/evaluacion")
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["estado"] == "BORRADOR"
    por_id = {x["ajuste_id"]: x for x in j["sintesis"]["ajustes"]}
    assert [e["semaforo"] for e in por_id[a[1].id]["evolucion"]] == ["ROJO", "AMARILLO", "ROJO"]
    assert por_id[a[0].id]["decision_sugerida"] == "MANTENER" and por_id[a[1].id]["decision_sugerida"] in ("MODIFICAR", "RETIRAR")
    d6, d8 = j["sintesis"]["indicadores"]["D6"], j["sintesis"]["indicadores"]["D8"]
    assert d6["valor"] == 100.0 and d6["cumple"] is True and d6["meta"] == 80
    assert d8["valor"] == 50.0 and d8["cumple"] is False
    assert j["tendencia"]["series"][1]["valores"] == [2, 1, 2]
    assert j["puede_cerrar"] is False and {b["code"] for b in j["bloqueos_cierre"]} == {"DECISIONES_INCOMPLETAS", "VALORACION_INCOMPLETA"}
    assert api.post(w.bienestar, f"/planes/{plan.id}/evaluacion").status_code == 409


def test_decisiones_exigen_justificacion_y_no_se_mantiene_un_ajuste_en_rojo(ctx):
    api, w, plan, a = ctx
    _tres_cortes(api, w, plan, a)
    api.post(w.bienestar, f"/planes/{plan.id}/evaluacion")
    url = f"/planes/{plan.id}/evaluacion"
    assert api.patch(w.bienestar, url, {"decisiones": [{"ajuste_id": a[0].id, "tipo_decision": "MANTENER"}]}).status_code == 422
    assert api.patch(w.bienestar, url, {"decisiones": [{"ajuste_id": a[0].id, "tipo_decision": "MANTENER", "justificacion": "  "}]}).status_code == 422
    r = api.patch(w.bienestar, url, {"decisiones": [{"ajuste_id": a[1].id, "tipo_decision": "MANTENER", "justificacion": "Seguir igual"}]})
    assert r.status_code == 422 and r.json()["code"] == "DECISION_INCOMPATIBLE_ROJO"
    r = api.patch(w.bienestar, url, {"decisiones": [{"tipo_decision": "CREAR_NUEVO", "justificacion": "Nueva idea"}]})
    assert r.status_code == 422 and r.json()["code"] == "DESCRIPCION_REQUERIDA"
    r = api.patch(w.bienestar, url, {"decisiones": [{"ajuste_id": 99999, "tipo_decision": "RETIRAR", "justificacion": "No existe"}]})
    assert r.status_code == 404


def test_cierre_f9_completo_finaliza_plan_y_alimenta_cbr_anonimo(ctx, db):
    api, w, plan, a = ctx
    _tres_cortes(api, w, plan, a)
    api.post(w.bienestar, f"/planes/{plan.id}/evaluacion")
    url = f"/planes/{plan.id}/evaluacion"
    # cerrar incompleto -> 409
    r = api.post(w.bienestar, url + "/cerrar")
    assert r.status_code == 409 and r.json()["code"] in ("DECISIONES_INCOMPLETAS", "VALORACION_INCOMPLETA")
    r = api.patch(w.bienestar, url, {
        "efectividad_general": "MEDIA", "recomendaciones": "Reforzar el formato escrito", "lecciones_aprendidas": "Ubicación fue clave",
        "nuevas_barreras_identificadas": "Ruido del laboratorio", "fortalezas_emergentes": "Participa más",
        "valoracion_dimensiones": _valoracion(),
        "decisiones": [
            {"ajuste_id": a[0].id, "tipo_decision": "MANTENER", "justificacion": "Verde en los tres cortes", "lecciones_aprendidas": "Funciona"},
            {"ajuste_id": a[1].id, "tipo_decision": "RETIRAR", "justificacion": "Rojo en C3", "lecciones_aprendidas": "No era claro"},
            {"tipo_decision": "CREAR_NUEVO", "descripcion_decision": "Guía visual paso a paso", "justificacion": "Reemplaza el retirado"},
        ]})
    assert r.status_code == 200, r.text
    assert r.json()["puede_cerrar"] is True and len(r.json()["decisiones"]) == 3
    # repetir el mismo PATCH no duplica decisiones
    r = api.patch(w.bienestar, url, {"decisiones": [{"tipo_decision": "CREAR_NUEVO", "descripcion_decision": "Guía visual paso a paso", "justificacion": "Igual"}]})
    assert len(r.json()["decisiones"]) == 3
    r = api.post(w.bienestar, url + "/cerrar")
    assert r.status_code == 200, r.text
    assert r.json()["plan_estado"] == "FINALIZADO" and r.json()["cbr"]["creados"] == 1
    db.refresh(plan)
    assert plan.estado == EstadoPlanEnum.FINALIZADO
    j = api.get(w.bienestar, url).json()
    assert j["estado"] == "CERRADA" and j["alimento_cbr"] is True and j["apoyos_efectivos"] and j["apoyos_a_discontinuar"]
    assert {d["estado_decision"] for d in j["decisiones"]} == {"ACORDADA"}
    # CBR: caso exitoso del ajuste VERDE con su estrategia, SIN identidad del estudiante
    caso = db.query(CasoCbr).one()
    assert caso.exitoso and str(caso.resultado_semaforo) == "VERDE" and caso.origen == "F9"
    texto = json.dumps(caso.perfil, ensure_ascii=False)
    assert set(caso.perfil) == {"tipos_barrera", "escenarios", "principios", "severidad_max", "tipo_ajuste"}
    for prohibido in (w.estudiante_user.nombre_completo, w.estudiante_user.email, w.estudiante.codigo_estudiante, "aq10", "diagn"):
        assert prohibido.lower() not in texto.lower()
    assert "estudiante_id" not in caso.perfil and "nombre" not in texto.lower()
    # cerrado: ya no se edita ni se cierra otra vez
    assert api.patch(w.bienestar, url, {"recomendaciones": "x"}).status_code == 409
    assert api.post(w.bienestar, url + "/cerrar").status_code == 409
    assert db.query(DecisionPlan).count() == 3


def test_cierre_exige_c3_cerrado(ctx):
    api, w, plan, a = ctx
    _corte(api, w, plan, "C1", [(a[0], "VERDE"), (a[1], "VERDE")])
    api.post(w.bienestar, f"/planes/{plan.id}/evaluacion")
    r = api.patch(w.bienestar, f"/planes/{plan.id}/evaluacion", {
        "valoracion_dimensiones": _valoracion(),
        "decisiones": [{"ajuste_id": x.id, "tipo_decision": "MANTENER", "justificacion": "Funciona bien"} for x in a]})
    assert r.status_code == 200
    r = api.post(w.bienestar, f"/planes/{plan.id}/evaluacion/cerrar")
    assert r.status_code == 409 and r.json()["code"] == "C3_NO_CERRADO"


def test_matriz_de_acceso_f9(ctx, db):
    api, w, plan, a = ctx
    _corte(api, w, plan, "C1", [(a[0], "VERDE"), (a[1], "VERDE")])
    assert api.post(w.bienestar, f"/planes/{plan.id}/evaluacion").status_code == 201
    url = f"/planes/{plan.id}/evaluacion"
    for u in (w.bienestar, w.coordinador, w.estudiante_user):  # lectura
        assert api.get(u, url).status_code == 200
    for u in (w.docente, w.familiar, w.admin, w.coordinador_otro, w.otro_estudiante_user):  # §12.1: sin acceso
        assert api.get(u, url).status_code == 403, u.rol
    for u in (w.coordinador, w.estudiante_user, w.docente):  # solo Bienestar escribe
        assert api.patch(u, url, {"recomendaciones": "x"}).status_code == 403
        assert api.post(u, url + "/cerrar").status_code == 403
    assert api.get(w.bienestar, "/planes/999999/evaluacion").status_code == 404
