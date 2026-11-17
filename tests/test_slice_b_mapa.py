"""F3 contexto (8 escenarios), F4 barreras (8 tipos, RF-19, gate F1), F5 facilitadores y vista cruzada."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import LogAuditoria
from app.models.base import utcnow  # noqa: F401
from app.models.enums import Escenario, TipoBarrera, TipoFacilitador, TipoHito
from app.models.mapa import BarreraIdentificada
from app.models.trayectoria import HitoTrayectoria
from tests.slice_b_helpers import fill_and_confirm_f1, h

API = "/api/v1"


def u(w, est=None):
    return f"{API}/estudiantes/{(est or w.estudiante).id}"


def barrera(tipo="COMUNICATIVA", escenario="AULA", **kw):
    return {"tipo_barrera": tipo, "escenario": escenario, "descripcion_barrera": "Las instrucciones se dan solo de forma oral.", **kw}


def test_barreras_exigen_caracterizacion_confirmada(client, world):
    w = world
    r = client.post(f"{u(w)}/barreras", json=barrera(), headers=h(w.bienestar))
    assert r.status_code == 409 and r.json()["code"] == "CARACTERIZACION_INCOMPLETA"
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    r = client.post(f"{u(w)}/barreras", json=barrera(detalle={"tipo_comunicacion_problema": "Instrucciones orales"}), headers=h(w.bienestar))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["tipo_barrera"] == "COMUNICATIVA" and j["detalle"]["tipo_comunicacion_problema"] == "Instrucciones orales"
    assert "entorno" in j["aviso"]


def test_ocho_tipos_con_subentidad_y_alias_tipo(client, db, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    detalles = {
        "ACTITUDINAL": {"tipo_actitud": "ESTIGMA"}, "COMUNICATIVA": {"descripcion_problema": "x"},
        "PEDAGOGICA": {"metodologia_problematica": "Clase magistral"}, "EVALUATIVA": {"aspecto_evaluativo": "TIEMPO"},
        "SENSORIAL": {"tipo_sensorial": "AUDITIVA", "hipersensibilidad": True},
        "SOCIAL": {"tipo_interaccion": "Trabajo en grupo", "propuesta_respuesta_institucional": "Formar grupos con roles definidos."},
        "INSTITUCIONAL": {"politica_procedimiento": "Matrícula presencial"}, "TECNOLOGICA": {"tipo_tecnologia": "Plataforma"},
    }
    assert set(detalles) == {t.value for t in TipoBarrera}
    for tipo, det in detalles.items():
        body = {"tipo": tipo, "escenario": "CAMPUS", "descripcion_barrera": "Descripción de la barrera.", "detalle": det}  # alias `tipo`
        r = client.post(f"{u(w)}/barreras", json=body, headers=h(w.bienestar))
        assert r.status_code == 201, (tipo, r.text)
        assert r.json()["detalle"], tipo
    assert client.get(f"{u(w)}/barreras", headers=h(w.bienestar)).json()["total"] == 8
    assert client.get(f"{u(w)}/barreras?tipo_barrera=SOCIAL", headers=h(w.bienestar)).json()["total"] == 1
    # detalle inválido para el tipo
    r = client.post(f"{u(w)}/barreras", json=barrera("SENSORIAL", detalle={"tipo_sensorial": "INVENTADO"}), headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "DETALLE_INVALIDO"
    r = client.post(f"{u(w)}/barreras", json=barrera("SENSORIAL"), headers=h(w.bienestar))  # tipo_sensorial es obligatorio
    assert r.status_code == 422


def test_rf19_barrera_social_exige_respuesta_institucional(client, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    for det in ({}, {"propuesta_respuesta_institucional": "   "}, {"tipo_interaccion": "Grupos"}):
        r = client.post(f"{u(w)}/barreras", json=barrera("SOCIAL", detalle=det), headers=h(w.bienestar))
        assert r.status_code == 422 and r.json()["code"] == "BARRERA_SOCIAL_SIN_RESPUESTA_INSTITUCIONAL", det
    ok = client.post(f"{u(w)}/barreras", json=barrera("SOCIAL", detalle={"propuesta_respuesta_institucional": "Sensibilización a docentes y pares."}), headers=h(w.bienestar))
    assert ok.status_code == 201
    bid = ok.json()["id"]
    # tampoco se puede vaciar al modificar
    r = client.patch(f"{API}/barreras/{bid}", json={"detalle": {"propuesta_respuesta_institucional": ""}}, headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "BARRERA_SOCIAL_SIN_RESPUESTA_INSTITUCIONAL"


def test_crud_soft_delete_persistente_y_auditoria(client, db, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    bid = client.post(f"{u(w)}/barreras", json=barrera(), headers=h(w.bienestar)).json()["id"]
    r = client.patch(f"{API}/barreras/{bid}", json={"severidad": "SEVERA", "impacto_aprendizaje": True}, headers=h(w.bienestar))
    assert r.json()["severidad"] == "SEVERA" and r.json()["impacto_aprendizaje"] is True
    p = client.post(f"{API}/barreras/{bid}/persistente", json={"observacion": "Persiste tras DUA"}, headers=h(w.bienestar))
    assert p.status_code == 200 and p.json()["estado"] == "PERSISTENTE"
    assert client.post(f"{API}/barreras/{bid}/persistente", json={}, headers=h(w.estudiante_user)).status_code == 403
    assert client.delete(f"{API}/barreras/{bid}", headers=h(w.bienestar)).status_code == 422  # motivo obligatorio
    assert client.delete(f"{API}/barreras/{bid}?motivo=Registrada por error", headers=h(w.bienestar)).status_code == 200
    assert client.get(f"{u(w)}/barreras", headers=h(w.bienestar)).json()["total"] == 0
    db.expire_all()
    b = db.scalar(select(BarreraIdentificada).execution_options(include_deleted=True))
    assert b.deleted_at is not None and b.deleted_reason == "Registrada por error"
    assert {"BARRERA_CREADA", "BARRERA_PERSISTENTE", "BARRERA_ARCHIVADA"} <= {a.accion for a in db.scalars(select(LogAuditoria))}


def test_matriz_barreras_facilitadores_contexto(client, db, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    bid = client.post(f"{u(w)}/barreras", json=barrera(), headers=h(w.bienestar)).json()["id"]
    for ok in (w.bienestar, w.coordinador, w.estudiante_user):
        assert client.get(f"{u(w)}/barreras", headers=h(ok)).status_code == 200, ok.rol
    for no in (w.docente, w.admin, w.familiar, w.otro_estudiante_user, w.coordinador_otro):
        assert client.get(f"{u(w)}/barreras", headers=h(no)).status_code == 403, no.rol
        assert client.get(f"{u(w)}/facilitadores", headers=h(no)).status_code == 403, no.rol
        assert client.get(f"{u(w)}/contexto/2026-II", headers=h(no)).status_code == 403, no.rol
    assert client.patch(f"{API}/barreras/{bid}", json={"severidad": "LEVE"}, headers=h(w.coordinador)).status_code == 403
    # el estudiante aporta barreras propias, pero no modifica las de Bienestar
    r = client.post(f"{u(w)}/barreras", json=barrera("SENSORIAL", detalle={"tipo_sensorial": "AUDITIVA"}), headers=h(w.estudiante_user))
    assert r.status_code == 201
    assert client.patch(f"{API}/barreras/{bid}", json={"severidad": "LEVE"}, headers=h(w.estudiante_user)).json()["code"] == "SOLO_PROPIOS"
    assert client.patch(f"{API}/barreras/{r.json()['id']}", json={"severidad": "SEVERA"}, headers=h(w.estudiante_user)).status_code == 200


def test_facilitadores_vinculos_y_resumen_cruzado(client, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    b1 = client.post(f"{u(w)}/barreras", json=barrera(), headers=h(w.bienestar)).json()["id"]
    b2 = client.post(f"{u(w)}/barreras", json=barrera("SENSORIAL", "CAMPUS", detalle={"tipo_sensorial": "AUDITIVA"}), headers=h(w.bienestar)).json()["id"]
    assert {t.value for t in TipoFacilitador} == {"PERSONAL", "PEDAGOGICO", "SOCIAL", "INSTITUCIONAL", "TECNOLOGICO"}
    r = client.post(f"{u(w)}/facilitadores", headers=h(w.bienestar), json={
        "tipo": "TECNOLOGICO", "nombre_facilitador": "Lector de pantalla", "descripcion_detallada": "Lee los textos en voz alta.",
        "detalle": {"tipo_tecnologia": "Lector", "disponibilidad": "GRATUITA"}, "barreras_mitigadas": [b1]})
    assert r.status_code == 201, r.text
    f1 = r.json()
    assert f1["barreras_mitigadas"] == [b1] and f1["detalle"]["disponibilidad"] == "GRATUITA"
    f2 = client.post(f"{u(w)}/facilitadores", headers=h(w.bienestar), json={
        "tipo_facilitador": "PERSONAL", "nombre_facilitador": "Constancia", "descripcion_detallada": "Es muy constante."}).json()
    # vínculo reemplazable
    r = client.put(f"{API}/facilitadores/{f2['id']}/barreras", json={"barrera_ids": [b1, b2]}, headers=h(w.bienestar))
    assert sorted(r.json()["barreras_mitigadas"]) == [b1, b2]
    r = client.patch(f"{API}/facilitadores/{f2['id']}", json={"barreras_mitigadas": [b2]}, headers=h(w.bienestar))
    assert r.json()["barreras_mitigadas"] == [b2]
    # barrera de otro estudiante: 422
    r = client.put(f"{API}/facilitadores/{f2['id']}/barreras", json={"barrera_ids": [99999]}, headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "BARRERAS_INVALIDAS"
    res = client.get(f"{u(w)}/resumen-barrera-facilitador", headers=h(w.bienestar)).json()
    por_id = {b["id"]: b for b in res["barreras"]}
    assert {x["id"] for x in por_id[b1]["facilitadores"]} == {f1["id"]} and {x["id"] for x in por_id[b2]["facilitadores"]} == {f2["id"]}
    assert res["totales"] == {"barreras": 2, "facilitadores": 2, "barreras_sin_facilitador": 0, "barreras_persistentes": 0}
    assert client.get(f"{u(w)}/resumen-barrera-facilitador", headers=h(w.docente)).status_code == 403
    assert client.delete(f"{API}/facilitadores/{f1['id']}?motivo=Ya no aplica", headers=h(w.bienestar)).status_code == 200
    assert client.get(f"{u(w)}/facilitadores", headers=h(w.bienestar)).json()["total"] == 1


def test_contexto_ocho_escenarios_progreso_y_matriz(client, world):
    w = world
    sem = "2026-II"
    cat = client.get(f"{API}/mapa/catalogos", headers=h(w.bienestar)).json()
    assert {e["valor"] for e in cat["escenarios"]} == {e.value for e in Escenario}
    assert client.get(f"{u(w)}/contexto/{sem}", headers=h(w.bienestar)).json()["code"] == "CONTEXTO_NO_ENCONTRADO"
    r = client.patch(f"{u(w)}/contexto/{sem}/escenarios/AULA", headers=h(w.bienestar),
                     json={"aplica": True, "descripcion_condiciones": "35 estudiantes, ruido de pasillo.", "numero_estudiantes": 35})
    assert r.status_code == 200 and r.json()["escenarios_decididos"] == 1
    r = client.patch(f"{u(w)}/contexto/{sem}/escenarios/PASANTIAS", json={"aplica": False}, headers=h(w.bienestar))
    assert r.json()["escenarios_completos"] == 2  # los que no aplican cuentan como decididos y completos
    # idempotente
    again = client.patch(f"{u(w)}/contexto/{sem}/escenarios/PASANTIAS", json={"aplica": False}, headers=h(w.bienestar))
    assert again.json() == r.json()
    for esc in ("CAMPUS", "VIRTUALIDAD", "LABORATORIOS", "PRACTICA_CLINICA", "PRACTICA_SALUD_PUBLICA", "EVENTOS"):
        client.patch(f"{u(w)}/contexto/{sem}/escenarios/{esc}", json={"aplica": True, "descripcion_condiciones": f"Condiciones de {esc}."}, headers=h(w.bienestar))
    client.patch(f"{u(w)}/contexto/{sem}/resumen", json={"resumen_contextual": "Aulas grandes.", "factores_de_riesgo": "Ruido"}, headers=h(w.bienestar))
    prog = client.get(f"{u(w)}/contexto/{sem}/progreso", headers=h(w.estudiante_user)).json()
    assert prog["completo"] and prog["porcentaje"] == 100
    # facetas transversales
    r = client.patch(f"{u(w)}/contexto/{sem}/docentes", headers=h(w.bienestar), json={"items": [{"nombre_docente": "Prof. X", "disposicion_ajustes": "RECEPTIVA"}]})
    assert r.status_code == 200 and len(r.json()) == 1
    r = client.patch(f"{u(w)}/contexto/{sem}/evaluacion", json={"claridad_criterios": "POCO_CLARA"}, headers=h(w.bienestar))
    assert r.json()["claridad_criterios"] == "POCO_CLARA"
    # Coordinador aporta en escenarios; el estudiante solo lee; docente no
    assert client.patch(f"{u(w)}/contexto/{sem}/escenarios/EVENTOS", json={"observaciones": "Hay salida tranquila"}, headers=h(w.coordinador)).status_code == 200
    assert client.patch(f"{u(w)}/contexto/{sem}/resumen", json={"resumen_contextual": "x"}, headers=h(w.coordinador)).status_code == 403
    assert client.patch(f"{u(w)}/contexto/{sem}/escenarios/EVENTOS", json={"observaciones": "x"}, headers=h(w.estudiante_user)).status_code == 403
    assert client.patch(f"{u(w)}/contexto/{sem}/escenarios/EVENTOS", json={"observaciones": "x"}, headers=h(w.coordinador_otro)).status_code == 403
    assert client.get(f"{u(w)}/contexto/{sem}", headers=h(w.estudiante_user)).status_code == 200
    assert client.get(f"{u(w)}/contexto/2026-3", headers=h(w.bienestar)).json()["code"] == "SEMESTRE_INVALIDO"
    assert client.get(f"{u(w)}/contextos", headers=h(w.bienestar)).json()["total"] == 1


def test_contexto_precarga_desde_semestre_anterior_y_f10(client, db, world):
    w = world
    client.patch(f"{u(w)}/contexto/2026-I/escenarios/AULA", json={"aplica": True, "descripcion_condiciones": "Aula grande"}, headers=h(w.bienestar))
    client.patch(f"{u(w)}/contexto/2026-I/resumen", json={"factores_protectores": "Buen vínculo con tutor"}, headers=h(w.bienestar))
    db.add(HitoTrayectoria(estudiante_id=w.estudiante.id, tipo_hito=TipoHito.INICIO_PRACTICAS, fecha_hito=date(2026, 8, 3)))
    db.commit()
    r = client.post(f"{u(w)}/contexto", json={"semestre_academico": "2026-II"}, headers=h(w.bienestar))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["precarga"]["origen_semestre"] == "2026-I" and "AULA" in j["precarga"]["escenarios_copiados"]
    assert j["escenarios"]["AULA"]["descripcion_condiciones"] == "Aula grande" and j["factores_protectores"] == "Buen vínculo con tutor"
    assert set(j["precarga"]["hitos_sugeridos"]) == {"PRACTICA_CLINICA", "PRACTICA_SALUD_PUBLICA"}
    assert client.post(f"{u(w)}/contexto", json={"semestre_academico": "2026-II"}, headers=h(w.bienestar)).json()["code"] == "CONTEXTO_YA_EXISTE"
