"""Slice C1: matriz F7, tasa de implementación y matriz de acceso por rol (§12.1) sobre el Plan MAAR-TEA."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import (
    Apoyo,
    CalendarioAcademico,
    ImplementacionApoyo,
    ResponsableApoyo,
)
from app.models.enums import EstadoImplementacion
from app.services import plan_builder
from tests.c1_support import SEMESTRE, Api, firmar_todos, hasta_firmas, seed_insumos
from tests.factories import authorize_familiar, make_estudiante


def _calendario(db, w):
    cal = CalendarioAcademico(semestre_academico=SEMESTRE, programa_id=w.programa.id, fecha_inicio=date(2026, 8, 3),
                              fecha_fin=date(2026, 12, 12), fecha_c1=date(2026, 9, 18), fecha_c2=date(2026, 10, 23),
                              fecha_c3=date(2026, 12, 4), activo=True)
    db.add(cal)
    db.commit()
    return cal


def test_matriz_sin_calendario_409_y_luego_generada(client, db, world):
    seed_insumos(db, world, calendario=False)
    api = Api(client)
    plan = hasta_firmas(api, world, semestre_academico=SEMESTRE)
    pid = plan["id"]
    res = firmar_todos(api, world, pid)
    # aprobado, pero la F7 queda pendiente por falta de calendario (no bloquea la aprobación)
    assert res["plan"]["estado"] == "APROBADO"
    assert res["matriz"]["generada"] is False and res["matriz"]["code"] == "CALENDARIO_NO_CONFIGURADO"
    r = api.post(f"/planes/{pid}/matriz", world.bienestar)
    assert r.status_code == 409 and r.json()["code"] == "CALENDARIO_NO_CONFIGURADO"
    assert api.post(f"/planes/{pid}/iniciar-implementacion", world.bienestar).json()["code"] == "MATRIZ_PENDIENTE"
    _calendario(db, world)
    r = api.post(f"/planes/{pid}/matriz", world.bienestar)
    assert r.status_code == 201, r.text
    m = r.json()
    n_esperado = len(plan["ajustes"]) + len(plan["estrategias_dua"])
    assert len(m["apoyos"]) == n_esperado
    assert [c["corte"] for c in m["calendario"]["cortes"]] == ["C1", "C2", "C3"]
    for ap in m["apoyos"]:
        assert "2026-08-03" <= ap["fecha_inicio"] <= ap["fecha_fin_prevista"] <= "2026-12-12"
        assert ap["responsable_principal"]["usuario"]["id"] and ap["recurso"]["descripcion_recurso"]
        # los cortes de cada apoyo son los del calendario que caen dentro de sus fechas
        assert ap["cortes"] and all(ap["fecha_inicio"] <= c["fecha"] <= ap["fecha_fin_prevista"] for c in ap["cortes"])
    assert any(ap["responsable_secundario"] for ap in m["apoyos"])
    # regenerar es idempotente (no duplica) y conserva ediciones manuales
    ap0 = m["apoyos"][0]
    r = api.patch(f"/planes/{pid}/matriz/apoyos/{ap0['id']}", world.coordinador,
                  {"fecha_fin_prevista": "2026-12-01", "frecuencia": "Quincenal", "recurso": {"descripcion_recurso": "Aula 204"},
                   "responsable_secundario_id": world.docente.id})
    assert r.status_code == 200, r.text
    editado = next(a for a in r.json()["apoyos"] if a["id"] == ap0["id"])
    assert editado["fecha_fin_prevista"] == "2026-12-01" and editado["recurso"]["descripcion_recurso"] == "Aula 204"
    assert editado["responsable_secundario"]["usuario"]["id"] == world.docente.id
    again = api.post(f"/planes/{pid}/matriz", world.bienestar).json()
    assert len(again["apoyos"]) == n_esperado
    assert next(a for a in again["apoyos"] if a["id"] == ap0["id"])["fecha_fin_prevista"] == "2026-12-01"
    # fechas fuera del calendario -> 422
    r = api.patch(f"/planes/{pid}/matriz/apoyos/{ap0['id']}", world.bienestar, {"fecha_fin_prevista": "2027-03-01"})
    assert r.status_code == 422 and r.json()["code"] == "FECHAS_FUERA_DE_CALENDARIO"
    # el estudiante lee la matriz pero no la edita
    assert api.get(f"/planes/{pid}/matriz", world.estudiante_user).status_code == 200
    assert api.patch(f"/planes/{pid}/matriz/apoyos/{ap0['id']}", world.estudiante_user, {"frecuencia": "x"}).status_code == 403
    assert api.post(f"/planes/{pid}/iniciar-implementacion", world.bienestar).json()["estado"] == "IMPLEMENTACION"


def test_tasa_de_implementacion(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = hasta_firmas(api, world)
    pid = plan["id"]
    firmar_todos(api, world, pid)
    apoyos = list(db.scalars(select(Apoyo).where(Apoyo.plan_id == pid).order_by(Apoyo.id)))
    assert len(apoyos) == 4 and plan_builder.tasa_implementacion(db, pid) == 0.0
    cal = db.scalar(select(CalendarioAcademico))
    for i, ap in enumerate(apoyos[:3]):  # 3 de 4 implementados = 75 %
        rid = db.scalar(select(ResponsableApoyo.id).where(ResponsableApoyo.apoyo_id == ap.id, ResponsableApoyo.es_principal.is_(True)))
        db.add(ImplementacionApoyo(responsable_apoyo_id=rid, fecha_implementacion=cal.fecha_c1 if i < 2 else cal.fecha_c3,
                                   estado=EstadoImplementacion.EJECUTADA))
    db.commit()
    r = plan_builder.resumen_implementacion(db, pid)
    assert r["total_apoyos"] == 4 and r["implementados"] == 3 and r["tasa"] == 75.0 and r["cumple_meta"] is False
    c2 = plan_builder.resumen_implementacion(db, pid, "C2")  # la 3.ª es posterior al C2
    assert c2["implementados"] == 2 and c2["tasa"] == 50.0 and c2["hasta"] == cal.fecha_c2.isoformat()
    r = api.get(f"/planes/{pid}/implementacion", world.coordinador, params={"corte": "C2"})
    assert r.status_code == 200 and r.json()["meta"] == 80.0
    assert api.get(f"/planes/{pid}/matriz", world.bienestar).json()["tasa_implementacion"]["tasa"] == 75.0


# ------------------------------------------------------------------------------------------------ RBAC
def test_vista_docente_sin_datos_clinicos_y_aceptacion(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    from tests.c1_support import crear_plan

    plan = crear_plan(api, world)
    pid = plan["id"]
    mio = plan["ajustes"][0]["id"]
    r = api.patch(f"/planes/{pid}/ajustes/{mio}", world.bienestar,
                  {"asignatura_id": world.asignatura.id, "responsable_id": world.docente.id})
    assert r.status_code == 200 and r.json()["ajuste"]["especificidad"] == "PARA_ASIGNATURA"
    # el docente no ve planes en borrador ni en concertación
    assert api.get(f"/planes/{pid}", world.docente).status_code == 403
    assert api.get("/planes", world.docente).json()["total"] == 0
    api.post(f"/planes/{pid}/enviar-a-estudiante", world.bienestar)
    det = api.get(f"/planes/{pid}", world.bienestar).json()
    from tests.c1_support import aceptar_todos

    aceptar_todos(api, world, det)
    api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar)
    api.post(f"/planes/{pid}/validar", world.coordinador, {})
    assert api.get(f"/planes/{pid}", world.docente).status_code == 403
    firmar_todos(api, world, pid)
    # ahora sí: solo SU ajuste y sin datos clínicos
    d = api.get(f"/planes/{pid}", world.docente)
    assert d.status_code == 200
    d = d.json()
    assert d["vista"] == "DOCENTE" and [a["id"] for a in d["ajustes"]] == [mio]
    a = d["ajustes"][0]
    assert "descripcion_barrera" not in a["barrera"] and "justificacion" not in a and "fortaleza" not in a
    for prohibido in ("participacion", "resumen_ejecutivo", "firmas", "negociaciones_abiertas", "hash_contenido"):
        assert prohibido not in d
    assert api.get("/planes", world.docente).json()["total"] == 1
    assert api.get(f"/planes/{pid}/ajustes/{plan['ajustes'][1]['id']}", world.docente).status_code == 403
    assert api.get(f"/planes/{pid}/firmas", world.docente).status_code == 403
    mat = api.get(f"/planes/{pid}/matriz", world.docente).json()
    assert [x["ajuste_id"] for x in mat["apoyos"]] == [mio]
    # aceptación de responsabilidades
    otro = plan["ajustes"][1]["id"]
    assert api.post(f"/planes/{pid}/ajustes/{otro}/aceptacion-docente", world.docente, {"acepta": True}).status_code == 403
    assert api.post(f"/planes/{pid}/ajustes/{mio}/aceptacion-docente", world.docente_otro, {"acepta": True}).status_code == 403
    r = api.post(f"/planes/{pid}/ajustes/{mio}/aceptacion-docente", world.docente, {"acepta": False})
    assert r.status_code == 422 and r.json()["code"] == "COMENTARIO_REQUERIDO"
    r = api.post(f"/planes/{pid}/ajustes/{mio}/aceptacion-docente", world.docente, {"acepta": True, "comentario": "Entendido"})
    assert r.status_code == 200 and r.json()["ajuste"]["aceptacion_docente"]["aceptado"] is True
    assert api.patch(f"/planes/{pid}/ajustes/{mio}", world.docente, {"frecuencia": "x"}).status_code == 403
    # el semáforo es solo lectura del último registro de seguimiento
    from app.models import RegistroSeguimientoAjuste, Seguimiento
    from app.models.enums import Corte, Semaforo

    seg = Seguimiento(estudiante_id=world.estudiante.id, plan_id=pid, corte=Corte.C1, fecha_seguimiento=date(2026, 9, 18),
                      profesional_responsable_id=world.bienestar.id)
    db.add(seg)
    db.flush()
    db.add(RegistroSeguimientoAjuste(seguimiento_id=seg.id, ajuste_id=mio, corte=Corte.C1, semaforo=Semaforo.AMARILLO,
                                     registrado_por_id=world.bienestar.id))
    db.commit()
    d = api.get(f"/planes/{pid}", world.docente).json()
    assert d["ajustes"][0]["semaforo"]["valor"] == "AMARILLO" and "concertar" in d["ajustes"][0]["semaforo"]["texto"]
    assert d["resumen"]["por_semaforo"] == {"AMARILLO": 1}


def test_matriz_de_acceso_plan(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    from tests.c1_support import crear_plan

    plan = crear_plan(api, world)
    pid, aid = plan["id"], plan["ajustes"][0]["id"]
    nuevo = {"tipo_ajuste": "AMBIENTE", "detalle": {"tipo": "ESPACIO_TRANQUILO"}, "nombre_ajuste": "Prueba x",
             "descripcion_ajuste": "descripción de prueba", "barrera_asociada_id": plan["ajustes"][0]["barrera"]["id"]}
    # escritura: solo Bienestar
    for u in (world.estudiante_user, world.coordinador, world.docente, world.familiar, world.admin):
        assert api.post(f"/planes/{pid}/ajustes", u, nuevo).status_code == 403, u.rol
        assert api.patch(f"/planes/{pid}", u, {"resumen_ejecutivo": "x"}).status_code == 403
    assert api.post(f"/estudiantes/{world.estudiante.id}/planes", world.coordinador).status_code == 403
    # el administrador no tiene acceso al plan (§12.1)
    assert api.get(f"/planes/{pid}", world.admin).status_code == 403
    assert api.get("/planes", world.admin).status_code == 403
    api.post(f"/planes/{pid}/enviar-a-estudiante", world.bienestar)
    # estudiante: solo el suyo
    otro_user, otro_est = make_estudiante(db, world.programa)
    assert api.get(f"/planes/{pid}", otro_user).status_code == 403
    assert api.get("/planes/mio", otro_user).status_code == 404
    assert api.get(f"/estudiantes/{world.estudiante.id}/planes", otro_user).status_code == 403
    assert api.get("/planes", world.estudiante_user).json()["total"] == 1
    assert api.get("/planes", otro_user).json()["total"] == 0
    # el estudiante no puede acciones de otros roles ni responder por otro
    assert api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", otro_user, {"respuesta": "ACEPTADO"}).status_code == 403
    assert api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.bienestar, {"respuesta": "ACEPTADO"}).status_code == 403
    # coordinador: lectura de su programa, no de otro
    assert api.get(f"/planes/{pid}", world.coordinador).status_code == 200
    assert api.get(f"/planes/{pid}", world.coordinador_otro).status_code == 403
    assert api.get("/planes", world.coordinador).json()["total"] == 1
    assert api.get("/planes", world.coordinador_otro).json()["total"] == 0
    # familiar: solo con autorización del estudiante (alcance PLAN), solo lectura
    assert api.get(f"/planes/{pid}", world.familiar).status_code == 403
    authorize_familiar(db, world.estudiante, world.familiar, ["CARACTERIZACION"])
    assert api.get(f"/planes/{pid}", world.familiar).status_code == 403  # alcance distinto
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    r = api.get(f"/planes/{pid}", world.familiar)
    assert r.status_code == 200 and r.json()["participacion"] == []
    assert api.post(f"/planes/{pid}/firmar", world.familiar, {"confirmo": True}).status_code == 403
    assert api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.familiar, {"respuesta": "ACEPTADO"}).status_code == 403
    assert api.get("/planes", world.familiar).json()["total"] == 1
    # sin sesión
    assert client.get(f"/api/v1/planes/{pid}").status_code == 401


def test_estudiante_sin_consentimiento_bloqueado(client, db, world):
    seed_insumos(db, world)
    u, _ = make_estudiante(db, world.programa, consent=False)
    api = Api(client)
    r = api.get("/planes/mio", u)
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
