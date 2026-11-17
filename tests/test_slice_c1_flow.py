"""Slice C1: borrador asistido, workflow de concertación, firmas, versiones y negociación."""

from __future__ import annotations

from sqlalchemy import select

from app.models import EmailOutbox, FirmaPlan, LogAuditoria, Notificacion, PlanMaarTea, PlanVersion
from app.models.enums import EstadoFirma
from app.models.sistema import ParametroSistema
from tests.c1_support import Api, aceptar_todos, crear_plan, firmar_todos, hasta_firmas, seed_insumos


def _ajuste_nuevo(w, barrera_id, **extra):
    return {"tipo_ajuste": "AMBIENTE", "detalle": {"tipo": "ESPACIO_TRANQUILO", "descripcion": "Sala aparte"},
            "nombre_ajuste": "Sala tranquila para exámenes", "descripcion_ajuste": "Presentar el examen en un salón silencioso",
            "barrera_asociada_id": barrera_id, "frecuencia": "Cada examen", "recurso": "Salón reservado", **extra}


def test_borrador_asistido(client, db, world):
    ins = seed_insumos(db, world)
    api = Api(client)
    r = api.post(f"/estudiantes/{world.estudiante.id}/planes", world.bienestar)
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    assert plan["estado"] == "BORRADOR" and plan["version"] == 1 and plan["semestre_academico"] == "2026-II"
    assert len(plan["ajustes"]) == 3
    cats = {a["tipo_ajuste"] for a in plan["ajustes"]}
    assert cats == {"AMBIENTE", "COMUNICACION", "EVALUACION"}
    for a in plan["ajustes"]:
        assert a["barrera"]["id"] in {b.id for b in ins["barreras"]}
        assert a["fortaleza"]["nombre_fortaleza"] == "Atención al detalle"
        assert a["origen"] == "BORRADOR_ASISTIDO" and a["propuesto_por"]["rol"] == "SISTEMA"
    amb = next(a for a in plan["ajustes"] if a["tipo_ajuste"] == "AMBIENTE")
    assert amb["detalle"]["tipo"] == "RUIDO_CONTROLADO"  # barrera sensorial auditiva
    assert len(plan["estrategias_dua"]) == 1
    assert plan["estrategias_dua"][0]["barrera"]["id"] == ins["barreras"][1].id
    # un plan activo por estudiante y semestre
    r2 = api.post(f"/estudiantes/{world.estudiante.id}/planes", world.bienestar)
    assert r2.status_code == 409 and r2.json()["code"] == "PLAN_ACTIVO_EXISTENTE" and r2.json()["plan_id"] == plan["id"]
    # el estudiante no ve el borrador
    r3 = api.get("/planes/mio", world.estudiante_user)
    assert r3.status_code == 404 and r3.json()["code"] == "SIN_PLAN"
    assert api.get(f"/planes/{plan['id']}", world.estudiante_user).status_code == 404


def test_ajuste_crud_y_categorias(client, db, world):
    ins = seed_insumos(db, world, sugerencia=False)
    api = Api(client)
    plan = crear_plan(api, world)
    pid = plan["id"]
    bid = ins["barreras"][0].id
    # barrera obligatoria
    body = _ajuste_nuevo(world, bid)
    body.pop("barrera_asociada_id")
    assert api.post(f"/planes/{pid}/ajustes", world.bienestar, body).status_code == 422
    # detalle de otra categoría
    bad = _ajuste_nuevo(world, bid, detalle={"tipo": "TIEMPO_EXTENDIDO"})
    r = api.post(f"/planes/{pid}/ajustes", world.bienestar, bad)
    assert r.status_code == 422 and r.json()["code"] == "DETALLE_AJUSTE_INVALIDO"
    # una por cada categoría
    casos = {"COMUNICACION": "INSTRUCCIONES_ESCRITAS", "PEDAGOGIA": "TUTORIAS", "EVALUACION": "DESCANSOS",
             "AMBIENTE": "UBICACION_ESPECIFICA", "INTERACCION": "ROL_DEFINIDO", "TECNOLOGIA": "HERRAMIENTA_ASISTIVA"}
    for cat, tipo in casos.items():
        det = {"tipo": tipo, "descripcion": "x"} | ({"soporte_tecnico_requerido": True} if cat == "TECNOLOGIA" else {})
        r = api.post(f"/planes/{pid}/ajustes", world.bienestar,
                     _ajuste_nuevo(world, bid, tipo_ajuste=cat, detalle=det, fortaleza_apoyo_id=ins["fortaleza"].id))
        assert r.status_code == 201, r.text
        a = r.json()["ajuste"]
        assert a["tipo_ajuste"] == cat and a["detalle"]["tipo"] == tipo
        assert a["propuesto_por"]["rol"] == "BIENESTAR"
    # editar reinicia la revisión del estudiante y registra quién modificó
    aid = r.json()["ajuste"]["id"]
    r = api.patch(f"/planes/{pid}/ajustes/{aid}", world.bienestar, {"frecuencia": "Semanal"})
    assert r.status_code == 200 and r.json()["ajuste"]["modificado_por"]["id"] == world.bienestar.id
    # soft delete con motivo
    r = api.delete(f"/planes/{pid}/ajustes/{aid}", world.bienestar, params={"motivo": "Ya no aplica"})
    assert r.status_code == 200
    det = api.get(f"/planes/{pid}", world.bienestar).json()
    assert aid not in [a["id"] for a in det["ajustes"]]
    log = [e for e in det["participacion"] if e["accion"] in ("PROPUSO", "MODIFICO", "ELIMINO")]
    assert any(e["accion"] == "ELIMINO" and e["entidad_id"] == aid for e in log)


def test_workflow_firmas_y_aprobacion(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan0 = crear_plan(api, world)
    pid = plan0["id"]
    # transiciones inválidas -> 409 con code
    r = api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar)
    assert r.status_code == 409 and r.json()["code"] == "TRANSICION_PLAN_INVALIDA"
    assert api.post(f"/planes/{pid}/validar", world.coordinador, {}).status_code == 409
    assert api.post(f"/planes/{pid}/firmar", world.estudiante_user, {"confirmo": True}).status_code in (404, 409)
    assert api.post(f"/planes/{pid}/enviar-a-estudiante", world.bienestar).status_code == 200
    # aún sin aceptación del estudiante: no pasa a validación
    r = api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar)
    assert r.status_code == 409 and r.json()["code"] == "PLAN_NO_LISTO_PARA_VALIDACION" and r.json()["razones"]
    plan = api.get("/planes/mio", world.estudiante_user).json()
    assert plan["estado"] == "EN_CONCERTACION" and "RESPONDER_AJUSTES" in plan["acciones_disponibles"]
    aceptar_todos(api, world, plan)
    assert api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar).status_code == 200
    assert db.scalar(select(Notificacion.id).where(Notificacion.usuario_id == world.coordinador.id,
                                                  Notificacion.tipo == "PLAN_LISTO_FIRMA")) is not None
    # el estudiante no puede validar; el coordinador de otro programa tampoco
    assert api.post(f"/planes/{pid}/validar", world.estudiante_user, {}).status_code == 403
    assert api.post(f"/planes/{pid}/validar", world.coordinador_otro, {}).status_code == 403
    r = api.post(f"/planes/{pid}/devolver", world.coordinador, {"comentarios": "Falta aclarar el recurso del ajuste 1"})
    assert r.status_code == 200 and r.json()["estado"] == "EN_CONCERTACION"
    d = api.get(f"/planes/{pid}", world.bienestar).json()
    assert d["comentarios_validacion"].startswith("Falta aclarar")
    assert api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar).status_code == 200
    r = api.post(f"/planes/{pid}/validar", world.coordinador, {"comentario": "Ok"})
    assert r.status_code == 200 and r.json()["estado"] == "PENDIENTE_FIRMAS" and len(r.json()["hash_version"]) == 64
    # firmas
    assert api.post(f"/planes/{pid}/firmar", world.estudiante_user, {"confirmo": False}).status_code == 422
    r = api.post(f"/planes/{pid}/firmar", world.estudiante_user, {"confirmo": True})
    assert r.status_code == 201 and r.json()["firma"]["rol_firmante"] == "ESTUDIANTE" and not r.json()["aprobado"]
    assert r.json()["firma"]["firmado_at"] and r.json()["firma"]["hash_documento"]
    dup = api.post(f"/planes/{pid}/firmar", world.estudiante_user, {"confirmo": True})
    assert dup.status_code == 409 and dup.json()["code"] == "FIRMA_YA_REGISTRADA"
    assert api.post(f"/planes/{pid}/firmar", world.docente, {"confirmo": True}).status_code == 403
    r = api.post(f"/planes/{pid}/firmar", world.bienestar, {"confirmo": True})
    assert r.json()["plan"]["estado"] == "PENDIENTE_FIRMAS"  # el plan solo pasa a APROBADO con las 3
    r = api.post(f"/planes/{pid}/firmar", world.coordinador, {"confirmo": True})
    assert r.status_code == 201 and r.json()["aprobado"] and r.json()["plan"]["estado"] == "APROBADO"
    assert r.json()["matriz"]["generada"] is True  # el calendario existe
    # notificación y auditoría
    assert db.scalar(select(EmailOutbox.id).where(EmailOutbox.evento == "PLAN_FIRMADO_APROBADO")) is not None
    acciones = {x.accion for x in db.scalars(select(LogAuditoria))}
    assert {"FIRMA_PLAN", "PLAN_CAMBIO_ESTADO"} <= acciones
    # lista de firmas y verificación
    f = api.get(f"/planes/{pid}/firmas", world.estudiante_user).json()
    assert len(f["firmas"]) == 3 and f["estado_firmas"]["completas"]
    v = api.get(f"/planes/{pid}/verificar", world.coordinador).json()
    assert v["integro"] and v["completo"] and v["firmas_validas"] == 3
    # corromper el contenido sin pasar por el API: la verificación lo detecta
    p = db.get(PlanMaarTea, pid)
    p.resumen_ejecutivo = "alterado directamente en BD"
    db.commit()
    v = api.get(f"/planes/{pid}/verificar", world.coordinador).json()
    assert not v["integro"] and not v["completo"]
    # implementación
    p.resumen_ejecutivo = None
    db.commit()
    r = api.post(f"/planes/{pid}/iniciar-implementacion", world.bienestar)
    assert r.status_code == 200 and r.json()["estado"] == "IMPLEMENTACION"


def test_editar_plan_aprobado_crea_version_e_invalida_firmas(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = hasta_firmas(api, world)
    pid = plan["id"]
    firmar_todos(api, world, pid)
    aid = plan["ajustes"][0]["id"]
    r = api.patch(f"/planes/{pid}/ajustes/{aid}", world.bienestar, {"frecuencia": "Dos veces por semana"})
    assert r.status_code == 200 and r.json()["plan"] == {"id": pid, "estado": "EN_CONCERTACION", "version": 2, "nueva_version": True}
    firmas = list(db.scalars(select(FirmaPlan).where(FirmaPlan.plan_id == pid).order_by(FirmaPlan.id)))
    assert len(firmas) == 3 and all(f.estado == EstadoFirma.INVALIDADA and f.version == 1 for f in firmas)
    vs = api.get(f"/planes/{pid}/versiones", world.estudiante_user).json()
    assert [x["version"] for x in vs["items"]] == [2, 1] and vs["version_actual"] == 2
    v1 = next(x for x in vs["items"] if x["version"] == 1)
    assert v1["reemplazada"] and not v1["vigente"] and len(v1["firmas"]) == 3
    snap1 = api.get(f"/planes/{pid}/versiones/1", world.estudiante_user).json()
    assert snap1["snapshot"]["ajustes"][0]["frecuencia"] != "Dos veces por semana"
    snap2 = api.get(f"/planes/{pid}/versiones/2", world.estudiante_user).json()
    assert snap2["congelada"] is False and snap2["snapshot"]["ajustes"][0]["frecuencia"] == "Dos veces por semana"
    assert api.get(f"/planes/{pid}/versiones/9", world.estudiante_user).status_code == 404
    # historial inmutable: las filas de v1 siguen en BD (soft delete, no físico)
    pv = list(db.scalars(select(PlanVersion).where(PlanVersion.plan_id == pid).execution_options(include_deleted=True)))
    assert any(x.version == 1 and x.deleted_at is not None for x in pv)
    # la verificación de v1 sigue sirviendo (el snapshot coincide con lo que se firmó)
    ver = api.get(f"/planes/{pid}/verificar", world.coordinador).json()
    v1v = next(x for x in ver["versiones"] if x["version"] == 1)
    assert all(f["hash_coincide"] for f in v1v["firmas"])
    # el ajuste modificado necesita nueva aceptación del estudiante
    det = api.get("/planes/mio", world.estudiante_user).json()
    mod = next(a for a in det["ajustes"] if a["id"] == aid)
    assert mod["respuesta_estudiante"]["respuesta"] is None


def test_modificar_en_pendiente_firmas_invalida_firmas_existentes(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = hasta_firmas(api, world)
    pid = plan["id"]
    assert api.post(f"/planes/{pid}/firmar", world.estudiante_user, {"confirmo": True}).status_code == 201
    r = api.patch(f"/planes/{pid}", world.bienestar, {"resumen_ejecutivo": "Resumen actualizado"})
    assert r.status_code == 200 and r.json()["cambio"]["nueva_version"] and r.json()["plan"]["estado"] == "EN_CONCERTACION"
    f = db.scalars(select(FirmaPlan).where(FirmaPlan.plan_id == pid)).all()
    assert [x.estado for x in f] == [EstadoFirma.INVALIDADA]
    # un plan aprobado/archivado no admite ediciones de estados finales
    assert api.post(f"/planes/{pid}/archivar", world.bienestar, {"motivo": "Prueba de archivo"}).status_code == 200
    r = api.patch(f"/planes/{pid}", world.bienestar, {"resumen_ejecutivo": "otro"})
    assert r.status_code == 409 and r.json()["code"] == "PLAN_NO_EDITABLE"


def test_propuesta_de_modificacion_del_estudiante(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = crear_plan(api, world)
    pid = plan["id"]
    api.post(f"/planes/{pid}/enviar-a-estudiante", world.bienestar)
    aid = plan["ajustes"][0]["id"]
    r = api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.estudiante_user, {"respuesta": "MODIFICACION_PROPUESTA"})
    assert r.status_code == 422 and r.json()["code"] == "COMENTARIO_REQUERIDO"
    r = api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.estudiante_user,
                 {"respuesta": "MODIFICACION_PROPUESTA", "comentario": "Prefiero el aula 2, es más silenciosa"})
    assert r.status_code == 200
    d = api.get(f"/planes/{pid}", world.bienestar).json()
    a = next(x for x in d["ajustes"] if x["id"] == aid)
    assert a["respuesta_estudiante"]["modificacion_propuesta"].startswith("Prefiero")
    assert any(e["accion"] == "PROPUSO_MODIFICACION" and e["rol"] == "ESTUDIANTE" for e in d["participacion"])
    # mientras haya modificación pendiente no se puede enviar a validación
    aceptar_todos(api, world, {"id": pid, "ajustes": [x for x in plan["ajustes"] if x["id"] != aid]})
    r = api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar)
    assert r.status_code == 409
    # Bienestar incorpora (edita) y el estudiante acepta
    assert api.patch(f"/planes/{pid}/ajustes/{aid}", world.bienestar, {"descripcion_ajuste": "Aula 2, silenciosa"}).status_code == 200
    assert api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.estudiante_user, {"respuesta": "ACEPTADO"}).status_code == 200
    assert api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar).status_code == 200


# ------------------------------------------------------------------------------------------------ negociación
def _objetar(api, world, plan):
    pid, aid = plan["id"], plan["ajustes"][0]["id"]
    api.post(f"/planes/{pid}/enviar-a-estudiante", world.bienestar)
    r = api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.estudiante_user,
                 {"respuesta": "OBJETADO", "comentario": "No quiero cambiar de salón para los exámenes"})
    assert r.status_code == 200, r.text
    return pid, aid, r.json()["negociacion"]["id"]


def test_negociacion_tres_ciclos_escala_al_comite(client, db, world):
    seed_insumos(db, world)
    db.add(ParametroSistema(clave="comite_inclusion_emails", valor=["comite@unicordoba.example.com"], tipo="JSON"))
    db.commit()
    api = Api(client)
    plan = crear_plan(api, world)
    pid, aid, tid = _objetar(api, world, plan)
    assert api.get(f"/planes/{pid}", world.bienestar).json()["estado"] == "EN_NEGOCIACION"
    t = api.get(f"/negociacion/{tid}", world.bienestar).json()
    assert t["ciclo"] == 1 and t["estado"] == "ABIERTA" and t["max_ciclos"] == 3
    # el estudiante no puede responder antes de la contrapropuesta; ni objetar de nuevo el mismo ajuste
    assert api.post(f"/negociacion/{tid}/responder", world.estudiante_user, {"acepta": False, "comentario": "no"}).status_code == 409
    r = api.post(f"/planes/{pid}/ajustes/{aid}/respuesta-estudiante", world.estudiante_user, {"respuesta": "ACEPTADO"})
    assert r.status_code == 409 and r.json()["code"] == "AJUSTE_EN_NEGOCIACION"
    for ciclo in (1, 2, 3):
        r = api.post(f"/negociacion/{tid}/contrapropuesta", world.bienestar, {"propuesta": f"Contrapropuesta del ciclo {ciclo}"})
        assert r.status_code == 200 and r.json()["estado"] == "EN_CICLO" and r.json()["ciclo"] == ciclo
        r = api.post(f"/negociacion/{tid}/responder", world.estudiante_user,
                     {"acepta": False, "comentario": f"Sigo sin estar de acuerdo (ciclo {ciclo})"})
        assert r.status_code == 200, r.text
    t = r.json()
    assert t["estado"] == "ESCALADA_COMITE" and t["escalada_at"] and t["ciclo"] == 3
    assert [h["resolucion"] for h in t["historial"]] == ["SIN_ACUERDO"] * 3
    assert all(h["objecion"] and h["propuesta"] for h in t["historial"])
    plan_d = api.get(f"/planes/{pid}", world.bienestar).json()
    assert plan_d["estado"] == "ESCALADO_COMITE" and plan_d["ciclos_negociacion"] == 3
    # aviso al Comité (correo externo) y a los actores del plan
    outbox = list(db.scalars(select(EmailOutbox).where(EmailOutbox.evento == "NEGOCIACION_ESCALADA_COMITE")))
    assert "comite@unicordoba.example.com" in {o.destinatario_email for o in outbox}
    assert {o.usuario_id for o in outbox if o.usuario_id} >= {world.estudiante_user.id, world.bienestar.id}
    # ya no hay más ciclos: el estudiante no puede seguir respondiendo
    assert api.post(f"/negociacion/{tid}/responder", world.estudiante_user, {"acepta": True}).status_code == 409
    # no se puede enviar a validación con una negociación escalada
    assert api.post(f"/planes/{pid}/enviar-a-validacion", world.bienestar).status_code == 409
    # decisión del Comité registrada: el estudiante no cierra; el coordinador sí (escalada)
    assert api.post(f"/negociacion/{tid}/cerrar", world.estudiante_user, {"resultado": "ACORDADO", "resolucion": "x" * 6}).status_code == 403
    r = api.post(f"/negociacion/{tid}/cerrar", world.coordinador,
                 {"resultado": "MANTENER_POR_COMITE", "resolucion": "El Comité mantiene el ajuste con seguimiento en C1"})
    assert r.status_code == 200 and r.json()["estado"] == "CERRADA"
    assert api.get(f"/planes/{pid}", world.bienestar).json()["estado"] == "EN_CONCERTACION"
    listado = api.get("/negociacion", world.bienestar, params={"plan_id": pid}).json()
    assert listado["total"] == 1


def test_negociacion_acuerdo_en_segundo_ciclo_y_contrapropuesta_con_cambios(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = crear_plan(api, world)
    pid, aid, tid = _objetar(api, world, plan)
    r = api.post(f"/negociacion/{tid}/contrapropuesta", world.bienestar,
                 {"propuesta": "Sala tranquila solo en exámenes parciales", "cambios_ajuste": {"frecuencia": "Solo parciales"}})
    assert r.status_code == 200
    api.post(f"/negociacion/{tid}/responder", world.estudiante_user, {"acepta": False, "comentario": "Prefiero mi salón con tapones"})
    api.post(f"/negociacion/{tid}/contrapropuesta", world.bienestar, {"propuesta": "Su salón con tapones auditivos"})
    r = api.post(f"/negociacion/{tid}/responder", world.estudiante_user, {"acepta": True, "comentario": "De acuerdo"})
    assert r.status_code == 200 and r.json()["estado"] == "ACORDADA" and r.json()["ciclo"] == 2
    d = api.get(f"/planes/{pid}", world.bienestar).json()
    assert d["estado"] == "EN_CONCERTACION"
    a = next(x for x in d["ajustes"] if x["id"] == aid)
    assert a["aceptado_por_estudiante"] is True and a["frecuencia"] == "Solo parciales"


def test_max_ciclos_parametrizable(client, db, world):
    seed_insumos(db, world)
    db.add(ParametroSistema(clave="max_ciclos_negociacion", valor=1, tipo="ENTERO"))
    db.commit()
    api = Api(client)
    pid, aid, tid = _objetar(api, world, crear_plan(api, world))
    api.post(f"/negociacion/{tid}/contrapropuesta", world.bienestar, {"propuesta": "Propuesta única"})
    r = api.post(f"/negociacion/{tid}/responder", world.estudiante_user, {"acepta": False, "comentario": "No acepto"})
    assert r.json()["estado"] == "ESCALADA_COMITE" and r.json()["max_ciclos"] == 1
