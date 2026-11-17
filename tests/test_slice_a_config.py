"""Slice A: catálogo DUA, AQ-10 (config), calendario y parámetros del sistema."""

from __future__ import annotations

import io
import json

from sqlalchemy import select

from app.data import aq10 as aq10_data
from app.data.dua_cast import build_catalog
from app.models import CuestionarioAQ10, EstrategiaDuaCatalogo, LogAuditoria
from app.services import aq10_config, params

API = "/api/v1"


def _seed_catalogo(db):
    for item in build_catalog():
        db.add(EstrategiaDuaCatalogo(**item))
    db.commit()


def _seed_aq10(db):
    c = CuestionarioAQ10(nombre="AQ-10", version="1.0", idioma="es-CO", fuente=aq10_data.FUENTE, items=aq10_data.items_json(),
                         opciones=aq10_data.opciones_json(), punto_corte=6, revision_linguistica_pendiente=True, activo=True)
    db.add(c)
    db.commit()
    return c


def _file(text: str, name: str, ctype: str):
    return {"archivo": (name, io.BytesIO(text.encode("utf-8")), ctype)}


# ----------------------------------------------------------------------------- catálogo DUA
def test_catalogo_lectura_por_rol_y_filtros(client, db, world, auth):
    _seed_catalogo(db)
    for u in (world.admin, world.bienestar, world.coordinador, world.docente):
        assert client.get(f"{API}/catalogo-dua/estrategias", headers=auth(u)).status_code == 200
    for u in (world.estudiante_user, world.familiar):
        assert client.get(f"{API}/catalogo-dua/estrategias", headers=auth(u)).status_code == 403
    h = auth(world.docente)
    todo = client.get(f"{API}/catalogo-dua/estrategias?page_size=100", headers=h).json()
    assert todo["total"] >= 30
    rep = client.get(f"{API}/catalogo-dua/estrategias?principio=REPRESENTACION&page_size=100", headers=h).json()
    assert 0 < rep["total"] < todo["total"] and all(i["principio"] == "REPRESENTACION" for i in rep["items"])
    lab = client.get(f"{API}/catalogo-dua/estrategias?escenario=LABORATORIOS&tipo_barrera=SENSORIAL&page_size=100", headers=h).json()
    assert lab["total"] > 0 and all("LABORATORIOS" in i["escenarios"] and "SENSORIAL" in i["tipos_barrera"] for i in lab["items"])
    p2 = client.get(f"{API}/catalogo-dua/estrategias?pauta=2", headers=h).json()
    assert all(i["pauta"] == 2 for i in p2["items"])
    assert client.get(f"{API}/catalogo-dua/estrategias?pauta=12", headers=h).status_code == 422
    pr = client.get(f"{API}/catalogo-dua/principios", headers=h).json()
    assert len(pr["principios"]) == 3 and sum(len(p["pautas"]) for p in pr["principios"]) == 9


def test_catalogo_crud_activar_inactivar(client, db, world, auth):
    h = auth(world.admin)
    body = {"codigo": "DUA-T-01", "nombre": "Estrategia de prueba", "descripcion_pedagogica": "Descripción pedagógica de prueba",
            "principio": "PARTICIPACION", "pauta": 7, "punto_verificacion": "7.3", "escenarios": ["AULA"], "tipos_barrera": ["SENSORIAL"]}
    r = client.post(f"{API}/catalogo-dua/estrategias", headers=h, json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert r.json()["pauta_nombre"]  # se completa desde CAST 2.2
    assert client.post(f"{API}/catalogo-dua/estrategias", headers=h, json=body).json()["code"] == "CODIGO_DUPLICADO"
    bad = client.post(f"{API}/catalogo-dua/estrategias", headers=h, json={**body, "codigo": "X", "pauta": 2})
    assert bad.status_code == 422  # pauta 2 es de REPRESENTACION
    assert client.post(f"{API}/catalogo-dua/estrategias", headers=auth(world.bienestar), json=body).status_code == 403
    up = client.patch(f"{API}/catalogo-dua/estrategias/{eid}", headers=h, json={"nombre": "Nombre nuevo", "escenarios": ["AULA", "CAMPUS"]})
    assert up.status_code == 200 and up.json()["escenarios"] == ["AULA", "CAMPUS"]
    assert client.patch(f"{API}/catalogo-dua/estrategias/{eid}", headers=h, json={"punto_verificacion": "2.1"}).status_code == 422
    ina = client.post(f"{API}/catalogo-dua/estrategias/{eid}/inactivar", headers=h)
    assert ina.json()["activo"] is False
    assert client.get(f"{API}/catalogo-dua/estrategias/{eid}", headers=auth(world.docente)).status_code == 404
    assert client.get(f"{API}/catalogo-dua/estrategias?activa=false", headers=h).json()["total"] == 1
    assert client.get(f"{API}/catalogo-dua/estrategias", headers=auth(world.docente)).json()["total"] == 0  # solo activas
    assert client.post(f"{API}/catalogo-dua/estrategias/{eid}/activar", headers=h).json()["activo"] is True
    assert client.delete(f"{API}/catalogo-dua/estrategias/{eid}", headers=h).status_code == 204
    assert client.get(f"{API}/catalogo-dua/estrategias/{eid}", headers=h).status_code == 404
    acciones = {a.accion for a in db.scalars(select(LogAuditoria))}
    assert {"CATALOGO_DUA_CREADO", "CATALOGO_DUA_MODIFICADO", "CATALOGO_DUA_INACTIVADO", "CATALOGO_DUA_ARCHIVADO"} <= acciones


CSV_DUA = ("codigo,nombre,descripcion_pedagogica,principio,pauta,punto_verificacion,escenarios,tipos_barrera,activo\n"
           "IMP-1,Uno,Descripción uno larga,REPRESENTACION,1,1.1,AULA|LABORATORIOS,SENSORIAL,1\n"
           "IMP-2,Dos,Descripción dos larga,ACCION_EXPRESION,4,4.1,VIRTUALIDAD,COMUNICATIVA|EVALUATIVA,0\n"
           "IMP-3,Tres,,PARTICIPACION,9,9.9,MARTE,NADA,1\n")


def test_catalogo_importar_csv_dry_run_y_real(client, db, world, auth):
    h = auth(world.admin)
    dry = client.post(f"{API}/catalogo-dua/estrategias/importar", headers=h, files=_file(CSV_DUA, "c.csv", "text/csv")).json()
    assert dry["dry_run"] is True and dry["nuevas"] == 2 and dry["con_errores"] == 1
    campos = {e["campo"] for e in dry["errores"] if e["fila"] == 4}
    assert {"descripcion_pedagogica", "escenarios", "tipos_barrera"} <= campos
    assert db.query(EstrategiaDuaCatalogo).count() == 0
    r = client.post(f"{API}/catalogo-dua/estrategias/importar?dry_run=false", headers=h, files=_file(CSV_DUA, "c.csv", "text/csv"))
    assert r.status_code == 422 and r.json()["code"] == "CSV_CON_ERRORES"
    ok = client.post(f"{API}/catalogo-dua/estrategias/importar?dry_run=false&omitir_errores=true", headers=h, files=_file(CSV_DUA, "c.csv", "text/csv"))
    assert ok.json()["creadas"] == 2
    db.expire_all()
    assert db.query(EstrategiaDuaCatalogo).filter_by(codigo="IMP-2").one().activo is False
    # idempotente; con actualizar_existentes modifica
    again = client.post(f"{API}/catalogo-dua/estrategias/importar?dry_run=false&omitir_errores=true", headers=h, files=_file(CSV_DUA, "c.csv", "text/csv")).json()
    assert again["creadas"] == 0 and again["existentes_omitidas"] == 2
    upd = CSV_DUA.replace("Uno,", "Uno editado,")
    u = client.post(f"{API}/catalogo-dua/estrategias/importar?dry_run=false&omitir_errores=true&actualizar_existentes=true", headers=h, files=_file(upd, "c.csv", "text/csv")).json()
    assert u["modificadas"] == 2
    db.expire_all()
    assert db.query(EstrategiaDuaCatalogo).filter_by(codigo="IMP-1").one().nombre == "Uno editado"
    assert client.post(f"{API}/catalogo-dua/estrategias/importar", headers=auth(world.bienestar), files=_file(CSV_DUA, "c.csv", "text/csv")).status_code == 403


def test_catalogo_importar_json_y_exportar(client, db, world, auth):
    h = auth(world.admin)
    data = {"estrategias": [{"codigo": "J-1", "nombre": "Json uno", "descripcion_pedagogica": "Descripción en json", "principio": "PARTICIPACION",
                             "pauta": 8, "escenarios": ["EVENTOS"], "tipos_barrera": ["SOCIAL"]}]}
    r = client.post(f"{API}/catalogo-dua/estrategias/importar?dry_run=false", headers=h, files=_file(json.dumps(data), "c.json", "application/json"))
    assert r.status_code == 200 and r.json()["creadas"] == 1
    malo = client.post(f"{API}/catalogo-dua/estrategias/importar", headers=h, files=_file("{no es json", "c.json", "application/json"))
    assert malo.status_code == 422 and malo.json()["code"] == "JSON_INVALIDO"
    ej = client.get(f"{API}/catalogo-dua/estrategias/exportar?formato=json", headers=h)
    assert json.loads(ej.text)["estrategias"][0]["codigo"] == "J-1"
    ec = client.get(f"{API}/catalogo-dua/estrategias/exportar?formato=csv", headers=auth(world.bienestar))
    assert ec.status_code == 200 and "J-1" in ec.text and "codigo" in ec.text.splitlines()[0]
    # round-trip: lo exportado se puede reimportar sin errores
    rt = client.post(f"{API}/catalogo-dua/estrategias/importar", headers=h, files=_file(ec.text, "x.csv", "text/csv")).json()
    assert rt["con_errores"] == 0 and rt["existentes_omitidas"] == 1
    assert client.get(f"{API}/catalogo-dua/estrategias/exportar", headers=auth(world.docente)).status_code == 403


# ----------------------------------------------------------------------------- AQ-10
def _payload(**over):
    p = {"items": aq10_data.items_json(), "opciones": aq10_data.opciones_json(), "instrucciones": "Responda con calma.",
         "revision_linguistica_pendiente": False}
    p.update(over)
    return p


def test_aq10_get_y_permisos(client, db, world, auth):
    _seed_aq10(db)
    r = client.get(f"{API}/admin/aq10", headers=auth(world.admin))
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) == 10 and len(j["opciones"]) == 4 and j["punto_corte"] == 6 and j["revision_linguistica_pendiente"] is True
    assert j["instrucciones"] and j["versiones"][0]["activo"] is True
    for u in (world.bienestar, world.docente, world.estudiante_user, world.coordinador):
        assert client.get(f"{API}/admin/aq10", headers=auth(u)).status_code == 403


def test_aq10_validaciones(client, db, world, auth):
    _seed_aq10(db)
    h = auth(world.admin)
    items = aq10_data.items_json()
    assert client.put(f"{API}/admin/aq10", headers=h, json=_payload(items=items[:9])).json()["code"] == "AQ10_ITEMS_INVALIDOS"
    dup = [dict(i) for i in items]
    dup[9]["numero"] = 1
    assert client.put(f"{API}/admin/aq10", headers=h, json=_payload(items=dup)).json()["code"] == "AQ10_ITEMS_INVALIDOS"
    assert client.put(f"{API}/admin/aq10", headers=h, json=_payload(opciones=aq10_data.opciones_json()[:3])).json()["code"] == "AQ10_OPCIONES_INVALIDAS"
    tres = [dict(o) for o in aq10_data.opciones_json()]
    tres[0]["direccion"] = "DESACUERDO"
    assert client.put(f"{API}/admin/aq10", headers=h, json=_payload(opciones=tres)).json()["code"] == "AQ10_OPCIONES_INVALIDAS"
    malo = [dict(i) for i in items]
    malo[0]["puntua_si"] = "TAL VEZ"
    assert client.put(f"{API}/admin/aq10", headers=h, json=_payload(items=malo)).status_code == 422
    db.expire_all()
    assert db.query(CuestionarioAQ10).count() == 1  # nada se guardó


def test_aq10_versiona_sin_alterar_historico(client, db, world, auth):
    viejo = _seed_aq10(db)
    items_viejos = list(viejo.items)
    h = auth(world.admin)
    nuevos = aq10_data.items_json()
    nuevos[0]["texto"] = "Texto revisado lingüísticamente."
    nuevos[0]["puntua_si"] = "DESACUERDO"
    r = client.put(f"{API}/admin/aq10", headers=h, json=_payload(items=nuevos))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == "2.0" and j["items"][0]["texto"].startswith("Texto revisado") and j["revision_linguistica_pendiente"] is False
    assert j["instrucciones"] == "Responda con calma."
    db.expire_all()
    rows = db.query(CuestionarioAQ10).order_by(CuestionarioAQ10.id).all()
    assert [r.activo for r in rows] == [False, True]
    assert rows[0].items == items_viejos  # la versión anterior queda intacta
    cfg = aq10_config.get_active_config(db)
    assert cfg.version == "2.0" and cfg.items[0]["puntua_si"] == "DESACUERDO" and cfg.punto_corte == 6
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "AQ10_CONFIG_ACTUALIZADA"))


def test_aq10_punto_corte(client, db, world, auth):
    _seed_aq10(db)
    h = auth(world.admin)
    for malo in (0, 11, -1):
        r = client.put(f"{API}/admin/aq10/punto-corte", headers=h, json={"punto_corte": malo})
        assert r.status_code == 422 and r.json()["code"] == "AQ10_PUNTO_CORTE_INVALIDO"
    assert client.put(f"{API}/admin/aq10/punto-corte", headers=h, json={"punto_corte": 7}).status_code == 200
    db.expire_all()
    assert params.get_param(db, "aq10_punto_corte") == 7 and aq10_config.get_active_config(db).punto_corte == 7
    assert client.get(f"{API}/admin/aq10", headers=h).json()["punto_corte"] == 7
    assert client.put(f"{API}/admin/aq10/punto-corte", headers=auth(world.bienestar), json={"punto_corte": 5}).status_code == 403
    ev = db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "PARAMETRO_MODIFICADO")).all()
    assert ev[-1].detalle["anterior"] in (6, None) and ev[-1].detalle["nuevo"] == 7


def test_aq10_sin_configurar_es_404(client, world, auth):
    r = client.get(f"{API}/admin/aq10", headers=auth(world.admin))
    assert r.status_code == 404 and r.json()["code"] == "AQ10_NO_CONFIGURADO"


# ----------------------------------------------------------------------------- calendario
def _cal(**over):
    c = {"semestre_academico": "2026-II", "fecha_inicio": "2026-08-03", "fecha_fin": "2026-12-05", "fecha_c1": "2026-09-17",
         "fecha_c2": "2026-10-21", "fecha_c3": "2026-11-25"}
    c.update(over)
    return c


def test_calendario_crud_y_validaciones(client, db, world, auth):
    h = auth(world.admin)
    r = client.post(f"{API}/calendario", headers=h, json=_cal(activo=True, fecha_inicio_practicas="2026-08-10"))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["activo"] is True and j["umbral_inasistencia"] == 20.0 and j["advertencias"] == []
    assert j["semanas_cortes"] == {"fecha_c1": "7", "fecha_c2": "12", "fecha_c3": "17"} and j["fecha_inicio_practicas"] == "2026-08-10"
    assert client.post(f"{API}/calendario", headers=h, json=_cal()).json()["code"] == "CALENDARIO_DUPLICADO"
    orden = client.post(f"{API}/calendario", headers=h, json=_cal(semestre_academico="2027-I", fecha_c1="2026-10-30"))
    assert orden.status_code == 422 and orden.json()["code"] == "CALENDARIO_INVALIDO"
    assert client.post(f"{API}/calendario", headers=h, json=_cal(semestre_academico="2027-I", fecha_fin="2026-07-01")).status_code == 422
    fuera = client.post(f"{API}/calendario", headers=h, json=_cal(semestre_academico="2027-I", fecha_inicio_practicas="2027-01-01"))
    assert fuera.status_code == 422
    aviso = client.post(f"{API}/calendario", headers=h, json=_cal(semestre_academico="2027-I", fecha_c1="2026-08-20"))
    assert aviso.status_code == 201 and len(aviso.json()["advertencias"]) == 1  # semana 3: advierte pero no bloquea
    assert client.post(f"{API}/calendario", headers=auth(world.bienestar), json=_cal(semestre_academico="2028-I")).status_code == 403
    cid = j["id"]
    p = client.patch(f"{API}/calendario/{cid}", headers=h, json={"umbral_inasistencia": 25, "fecha_c3": "2026-11-27"})
    assert p.status_code == 200 and p.json()["umbral_inasistencia"] == 25.0 and p.json()["fecha_c3"] == "2026-11-27"
    assert client.patch(f"{API}/calendario/{cid}", headers=h, json={"fecha_c1": "2026-11-01"}).status_code == 422


def test_calendario_semestre_activo_unico_y_lectura(client, db, world, auth):
    h = auth(world.admin)
    a = client.post(f"{API}/calendario", headers=h, json=_cal(activo=True)).json()["id"]
    b = client.post(f"{API}/calendario", headers=h, json=_cal(semestre_academico="2027-I", fecha_inicio="2027-02-01", fecha_fin="2027-06-05",
                                                              fecha_c1="2027-03-18", fecha_c2="2027-04-22", fecha_c3="2027-05-27")).json()["id"]
    assert client.get(f"{API}/calendario/activo", headers=auth(world.estudiante_user)).json()["id"] == a
    assert client.post(f"{API}/calendario/{b}/activar", headers=h).json()["activo"] is True
    assert client.get(f"{API}/calendario/activo", headers=auth(world.docente)).json()["id"] == b
    assert [c["id"] for c in client.get(f"{API}/calendario?solo_activos=true", headers=auth(world.docente)).json()["items"]] == [b]
    # calendario propio del programa convive con el institucional
    pr = client.post(f"{API}/calendario", headers=h, json=_cal(programa_id=world.programa.id, activo=True)).json()["id"]
    assert client.get(f"{API}/calendario/activo?programa_id={world.programa.id}", headers=h).json()["id"] == pr
    assert client.get(f"{API}/calendario/activo", headers=h).json()["id"] == b
    assert client.delete(f"{API}/calendario/{b}", headers=h).json()["code"] == "CALENDARIO_ACTIVO"
    assert client.delete(f"{API}/calendario/{a}", headers=h).status_code == 204
    assert client.get(f"{API}/calendario/activo", headers=auth(world.familiar)).status_code == 200
    assert client.get(f"{API}/calendario").status_code == 401


# ----------------------------------------------------------------------------- parámetros
def test_parametros_listar_validar_y_auditar(client, db, world, auth):
    h = auth(world.admin)
    lista = client.get(f"{API}/calendario/parametros", headers=h).json()["items"]
    claves = {p["clave"] for p in lista}
    assert {"umbral_inasistencia", "max_ciclos_negociacion", "aq10_punto_corte", "reportes_k_minimo"} <= claves
    assert client.get(f"{API}/calendario/parametros", headers=auth(world.coordinador)).status_code == 403
    ok = client.put(f"{API}/calendario/parametros/umbral_inasistencia", headers=h, json={"valor": 25})
    assert ok.status_code == 200 and ok.json()["valor"] == 25 and ok.json()["anterior"] == 20
    db.expire_all()
    assert params.get_param(db, "umbral_inasistencia") == 25
    malos = [("umbral_inasistencia", 0), ("umbral_inasistencia", "abc"), ("max_ciclos_negociacion", 4), ("max_ciclos_negociacion", 2.5),
             ("reportes_k_minimo", 2), ("comite_inclusion_email", "no-es-correo"), ("aq10_punto_corte", 11), ("dias_purga_sin_consentimiento", 3)]
    for clave, valor in malos:
        r = client.put(f"{API}/calendario/parametros/{clave}", headers=h, json={"valor": valor})
        assert r.status_code == 422 and r.json()["code"] == "PARAMETRO_INVALIDO", (clave, valor, r.text)
    assert client.put(f"{API}/calendario/parametros/inventado", headers=h, json={"valor": 1}).status_code == 404
    assert client.put(f"{API}/calendario/parametros/max_ciclos_negociacion", headers=auth(world.bienestar), json={"valor": 2}).status_code == 403
    assert client.put(f"{API}/calendario/parametros/comite_inclusion_email", headers=h, json={"valor": "comite@unicordoba.edu.co"}).status_code == 200
    ev = db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "PARAMETRO_MODIFICADO")).all()
    assert any(e.detalle["clave"] == "umbral_inasistencia" and e.detalle["anterior"] == 20 and e.detalle["nuevo"] == 25 for e in ev)
