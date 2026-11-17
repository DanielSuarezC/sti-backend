"""Panel del Docente (HU-23/24, D10): sin fuga de datos clinicos, alcance por asignatura, registro de implementacion."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models import (
    Apoyo,
    ImplementacionApoyo,
    ParametroSistema,
    RegistroImplementacion,
    RegistroSeguimientoAjuste,
    ResponsableApoyo,
)
from app.models.base import utcnow
from app.models.enums import Corte, EstadoPlanEnum, Semaforo, TipoParametro
from tests.c3_helpers import (
    CLAVES_PROHIBIDAS,
    agregar_estrategia,
    assert_sin_datos_clinicos,
    claves_recursivas,
    plan_con_datos_clinicos,
    segundo_ajuste,
)
from tests.factories import auth_headers, make_plan_with_ajuste


def _mis_ajustes(client, user):
    r = client.get("/api/v1/docente/mis-ajustes", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    return r.json()


def test_mis_ajustes_agrupa_por_asignatura_con_alias_y_sin_datos_clinicos(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    agregar_estrategia(db, plan, world)
    data = _mis_ajustes(client, world.docente)
    assert data["total_ajustes"] == 1 and data["total_estrategias"] == 1
    grupo = data["asignaturas"][0]
    assert grupo["asignatura"]["codigo"] == "ENF101"
    est = grupo["estudiantes"][0]
    assert est["alias"].startswith("Estudiante ") and est["iniciales"] is None
    a = est["ajustes"][0]
    assert a["id"] == ajuste.id and a["frecuencia"] == "Cada clase" and a["semaforo_actual"] == "AMARILLO"
    assert est["estrategias_dua"][0]["estado_implementacion"] == "PLANEADA"
    assert_sin_datos_clinicos(data)


def test_alias_estable_y_distinto_entre_docentes(client, db, world):
    plan_con_datos_clinicos(db, world)
    a1 = _mis_ajustes(client, world.docente)["asignaturas"][0]["estudiantes"][0]["alias"]
    a2 = _mis_ajustes(client, world.docente)["asignaturas"][0]["estudiantes"][0]["alias"]
    assert a1 == a2
    from app.services.docente_panel import mapa_alias

    assert mapa_alias(world.docente.id, {world.estudiante.id}) != mapa_alias(world.docente_otro.id, {world.estudiante.id})


def test_parametro_docente_ve_nombre_agrega_iniciales_pero_nunca_nombre(client, db, world):
    plan_con_datos_clinicos(db, world)
    db.add(ParametroSistema(clave="docente_ve_nombre", valor=True, tipo=TipoParametro.BOOLEANO))
    db.commit()
    data = _mis_ajustes(client, world.docente)
    assert data["docente_ve_nombre"] is True
    assert data["asignaturas"][0]["estudiantes"][0]["iniciales"] == "Z.Q.M."
    assert_sin_datos_clinicos(data)  # el nombre completo sigue prohibido


def test_detalle_ajuste_y_semaforo_sin_fuga(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    from app.models import Seguimiento

    seg = Seguimiento(estudiante_id=world.estudiante.id, plan_id=plan.id, corte=Corte.C1, fecha_seguimiento=date.today(),
                      profesional_responsable_id=world.bienestar.id)
    db.add(seg)
    db.flush()
    db.add(RegistroSeguimientoAjuste(
        seguimiento_id=seg.id, ajuste_id=ajuste.id, corte=Corte.C1, semaforo=Semaforo.ROJO, implementado=True,
        comentario_estudiante="CENTINELA_COMENTARIO_ESTUDIANTE", nueva_barrera_detectada="CENTINELA_DIAGNOSTICO",
        registrado_por_id=world.bienestar.id))
    ajuste.semaforo_actual = Semaforo.ROJO
    db.commit()
    h = auth_headers(world.docente)
    det = client.get(f"/api/v1/docente/ajustes/{ajuste.id}", headers=h)
    assert det.status_code == 200
    body = det.json()
    assert body["descripcion"] and body["frecuencia"] == "Cada clase" and body["indicador_efectividad"]
    assert body["semaforo_actual"] == "ROJO" and body["cortes"] == [{"corte": "C1", "semaforo": "ROJO", "implementado": True}]
    assert_sin_datos_clinicos(body)
    sem = client.get("/api/v1/docente/semaforo", headers=h)
    assert sem.status_code == 200
    assert sem.json()["resumen"]["ROJO"] == 1
    assert_sin_datos_clinicos(sem.json())


def test_docente_de_otra_asignatura_no_ve_ni_registra(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    h = auth_headers(world.docente_otro)
    assert _mis_ajustes(client, world.docente_otro)["total_ajustes"] == 0
    assert client.get(f"/api/v1/docente/ajustes/{ajuste.id}", headers=h).status_code in (403, 404)
    r = client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                    json={"implementado": True, "fecha": date.today().isoformat()})
    assert r.status_code in (403, 404)
    assert client.get(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h).status_code in (403, 404)
    assert db.scalars(select(ImplementacionApoyo)).all() == []


def test_otros_roles_no_entran_al_panel(client, db, world):
    plan_con_datos_clinicos(db, world)
    for u in (world.bienestar, world.coordinador, world.estudiante_user, world.familiar, world.admin):
        for ruta in ("/mis-ajustes", "/semaforo"):
            r = client.get(f"/api/v1/docente{ruta}", headers=auth_headers(u))
            assert r.status_code == 403 and r.json()["code"] == "ROL_NO_PERMITIDO"
    assert client.get("/api/v1/docente/mis-ajustes").status_code == 401


def test_planes_en_borrador_o_concertacion_no_aparecen(client, db, world):
    for estado in (EstadoPlanEnum.BORRADOR, EstadoPlanEnum.EN_CONCERTACION, EstadoPlanEnum.PENDIENTE_FIRMAS):
        plan, _ = make_plan_with_ajuste(db, world.estudiante, world.bienestar, asignatura=world.asignatura, estado=estado)
        assert _mis_ajustes(client, world.docente)["total_ajustes"] == 0
        plan.deleted_at = utcnow()
        db.commit()


def test_ajuste_de_otra_asignatura_del_mismo_plan_no_se_ve(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    otro = segundo_ajuste(db, plan, ajuste, asignatura_id=None)  # sin asignatura ni responsable = no es del docente
    data = _mis_ajustes(client, world.docente)
    ids = [a["id"] for g in data["asignaturas"] for e in g["estudiantes"] for a in e["ajustes"]]
    assert ids == [ajuste.id]
    r = client.get(f"/api/v1/docente/ajustes/{otro.id}", headers=auth_headers(world.docente))
    assert r.status_code == 404


def test_registro_implementacion_si_no_crea_cadena_f7(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    h = auth_headers(world.docente)
    hoy = date.today()
    r1 = client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                     json={"implementado": True, "fecha": hoy.isoformat(), "nota": "Se aplicó en el parcial"})
    assert r1.status_code == 201, r1.text
    assert r1.json()["implementado"] is True and r1.json()["nota"] == "Se aplicó en el parcial"
    r2 = client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                     json={"implementado": False, "fecha": (hoy - timedelta(days=1)).isoformat(), "nota": "No hubo clase"})
    assert r2.status_code == 201 and r2.json()["implementado"] is False
    hist = client.get(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h).json()
    assert [x["implementado"] for x in hist] == [True, False]  # más reciente primero
    apoyo = db.scalar(select(Apoyo).where(Apoyo.ajuste_id == ajuste.id))
    resp = db.scalar(select(ResponsableApoyo).where(ResponsableApoyo.apoyo_id == apoyo.id))
    assert resp.usuario_responsable_id == world.docente.id
    assert len(db.scalars(select(ImplementacionApoyo).where(ImplementacionApoyo.responsable_apoyo_id == resp.id)).all()) == 2
    assert len(db.scalars(select(RegistroImplementacion)).all()) == 2
    det = client.get(f"/api/v1/docente/ajustes/{ajuste.id}", headers=h).json()
    assert det["ultima_implementacion"]["implementado"] is True
    assert_sin_datos_clinicos(hist)


def test_implementacion_validaciones(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    h = auth_headers(world.docente)
    futuro = (date.today() + timedelta(days=3)).isoformat()
    r = client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                    json={"implementado": True, "fecha": futuro})
    assert r.status_code == 422 and r.json()["code"] == "FECHA_FUTURA"
    assert client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                       json={"fecha": date.today().isoformat()}).status_code == 422
    plan.estado = EstadoPlanEnum.FINALIZADO
    db.commit()
    r = client.post(f"/api/v1/docente/ajustes/{ajuste.id}/implementacion", headers=h,
                    json={"implementado": True, "fecha": date.today().isoformat()})
    assert r.status_code == 409 and r.json()["code"] == "PLAN_NO_IMPLEMENTABLE"
    assert client.get(f"/api/v1/docente/ajustes/{ajuste.id}", headers=h).status_code == 200  # FINALIZADO sigue visible


def test_estrategia_dua_transiciones(client, db, world):
    plan, _ = plan_con_datos_clinicos(db, world)
    e = agregar_estrategia(db, plan, world)
    h = auth_headers(world.docente)
    url = f"/api/v1/docente/estrategias/{e.id}/implementacion"
    r = client.post(url, headers=h, json={"estado": "INICIADA", "nota": "Empecé con la unidad 1"})
    assert r.status_code == 200 and r.json()["estado_implementacion"] == "INICIADA" and r.json()["implementada"] is False
    r = client.post(url, headers=h, json={"estado": "INICIADA"})
    assert r.status_code == 409 and r.json()["code"] == "TRANSICION_ESTRATEGIA_INVALIDA"
    r = client.post(url, headers=h, json={"estado": "IMPLEMENTADA", "nota": "Listo"})
    assert r.status_code == 200 and r.json()["implementada"] is True
    assert client.post(url, headers=h, json={"estado": "INICIADA"}).status_code == 409
    assert client.post(url, headers=h, json={"estado": "EVALUANDO"}).status_code == 422
    # otro docente: 404
    assert client.post(url, headers=auth_headers(world.docente_otro), json={"estado": "INICIADA"}).status_code == 404


def test_no_hay_claves_prohibidas_ni_en_el_esquema_openapi_de_salida(client, db, world):
    """Defensa en profundidad: los modelos de salida del panel son lista blanca (no declaran campos clinicos)."""
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for nombre in ("MisAjustesOut", "AjusteDocenteOut", "EstrategiaDocenteOut", "EstudianteAliasOut", "AjusteDetalleOut",
                   "SemaforoDocenteOut", "ImplementacionOut"):
        props = set(schemas[nombre]["properties"])
        assert not (props & CLAVES_PROHIBIDAS), (nombre, props & CLAVES_PROHIBIDAS)
    assert claves_recursivas({"a": [{"B": 1}]}) == {"a", "b"}
