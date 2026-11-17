"""F1/F2: secciones con guardado parcial idempotente, progreso, vista previa, confirmación, versionado, matriz y auditoría."""

from __future__ import annotations

from sqlalchemy import select, text

from app.models import LogAuditoria
from app.models.caracterizacion import Caracterizacion
from tests.factories import authorize_familiar
from tests.slice_b_helpers import F1_SECCIONES, fill_and_confirm_f1, h

API = "/api/v1"
F2 = {
    "fortalezas": {"items": [{"nombre_fortaleza": "Atención al detalle", "descripcion_detallada": "Detecta errores en registros."}]},
    "intereses": {"items": [{"nombre_interes": "Anatomía", "descripcion": "Dibuja estructuras."}]},
    "estrategias": {"items": [{"nombre_estrategia": "Esquemas", "descripcion": "Aprende con esquemas.", "tipo_estrategia": "VISUAL"}]},
    "metas": {"items": [{"tipo": "PROFESIONAL", "descripcion": "Trabajar en cuidados intensivos", "plazo": "5 años"}]},
}


def u(w, est=None):
    return f"{API}/estudiantes/{(est or w.estudiante).id}"


def test_guardado_parcial_idempotente_y_progreso(client, world):
    w = world
    prog = client.get(f"{u(w)}/caracterizacion/progreso", headers=h(w.bienestar)).json()
    assert prog["porcentaje"] == 0 and prog["estado"] == "INCOMPLETA" and not prog["puede_confirmar"]
    body = F1_SECCIONES["sensorial"]
    r1 = client.patch(f"{u(w)}/caracterizacion/sensorial", json=body, headers=h(w.bienestar))
    r2 = client.patch(f"{u(w)}/caracterizacion/sensorial", json=body, headers=h(w.bienestar))
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    ver = client.get(f"{u(w)}/caracterizacion", headers=h(w.bienestar)).json()
    assert len(ver["sensorial"]) == 1 and ver["version"] == 1 and ver["sensorial"][0]["tipo_sensorial"] == "AUDITIVA"
    # upsert por clave: actualiza, no duplica; `quitar` archiva
    client.patch(f"{u(w)}/caracterizacion/sensorial", headers=h(w.bienestar), json={"items": [
        {"tipo_sensorial": "AUDITIVA", "impacto_academico": "Pierde la concentración."}]})
    ver = client.get(f"{u(w)}/caracterizacion", headers=h(w.bienestar)).json()
    assert len(ver["sensorial"]) == 1 and ver["sensorial"][0]["impacto_academico"] == "Pierde la concentración."
    client.patch(f"{u(w)}/caracterizacion/sensorial", json={"quitar": ["AUDITIVA"]}, headers=h(w.bienestar))
    assert client.get(f"{u(w)}/caracterizacion", headers=h(w.bienestar)).json()["sensorial"] == []
    prog = client.get(f"{u(w)}/caracterizacion/progreso", headers=h(w.bienestar)).json()
    assert prog["porcentaje"] == 0


def test_confirmar_exige_secciones_y_crea_nueva_version_al_editar(client, db, world):
    w = world
    client.patch(f"{u(w)}/caracterizacion/resumen", json=F1_SECCIONES["resumen"], headers=h(w.bienestar))
    r = client.post(f"{u(w)}/caracterizacion/confirmar", headers=h(w.bienestar))
    assert r.status_code == 409 and r.json()["code"] == "FORMATO_INCOMPLETO" and r.json()["faltantes"]
    for sec, body in F1_SECCIONES.items():
        client.patch(f"{u(w)}/caracterizacion/{sec}", json=body, headers=h(w.bienestar))
    prog = client.get(f"{u(w)}/caracterizacion/progreso", headers=h(w.bienestar)).json()
    assert prog["porcentaje"] == 100 and prog["puede_confirmar"]
    prev = client.get(f"{u(w)}/caracterizacion/vista-previa", headers=h(w.bienestar)).json()
    assert any(b["titulo"] == "Perfil sensorial" for b in prev["bloques"]) and "entorno" in prev["aviso"]
    assert client.post(f"{u(w)}/caracterizacion/confirmar", headers=h(w.bienestar)).json()["estado"] == "COMPLETA"
    # editar tras confirmar => versión 2 INCOMPLETA; la 1 queda COMPLETA (historial)
    client.patch(f"{u(w)}/caracterizacion/resumen", json={"resumen_ejecutivo": "Actualizado."}, headers=h(w.bienestar))
    ver = client.get(f"{u(w)}/caracterizacion", headers=h(w.bienestar)).json()
    assert ver["version"] == 2 and ver["estado"] == "INCOMPLETA" and len(ver["sensorial"]) == 1
    rows = db.scalars(select(Caracterizacion).where(Caracterizacion.estudiante_id == w.estudiante.id).order_by(Caracterizacion.version)).all()
    assert [(c.version, str(c.estado)) for c in rows] == [(1, "COMPLETA"), (2, "INCOMPLETA")]


def test_voz_del_estudiante_edita_su_parte_y_comenta(client, db, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    r = client.patch(f"{u(w)}/caracterizacion/autodescripcion", json={"autodescripcion_estudiante": "Soy muy detallista."}, headers=h(w.estudiante_user))
    assert r.status_code == 200 and r.json()["estado"] == "EN_REVISION"
    ver = client.get(f"{u(w)}/caracterizacion", headers=h(w.estudiante_user)).json()
    assert ver["autodescripcion_estudiante"] == "Soy muy detallista." and ver["version"] == 2 and ver["estado"] == "EN_REVISION"
    # no edita las demás secciones
    r = client.patch(f"{u(w)}/caracterizacion/sensorial", json=F1_SECCIONES["sensorial"], headers=h(w.estudiante_user))
    assert r.status_code == 403 and r.json()["code"] == "SECCION_SOLO_BIENESTAR"
    r = client.post(f"{u(w)}/comentarios-formato", json={"formato": "F1", "seccion": "sensorial", "texto": "Falta mencionar la luz."}, headers=h(w.estudiante_user))
    assert r.status_code == 201
    assert client.get(f"{u(w)}/caracterizacion", headers=h(w.bienestar)).json()["comentarios"][0]["autor_rol"] == "ESTUDIANTE"
    # Bienestar re-confirma
    assert client.post(f"{u(w)}/caracterizacion/confirmar", headers=h(w.bienestar)).json()["estado"] == "COMPLETA"
    # estudiante no confirma ni edita lo de otro
    assert client.post(f"{u(w)}/caracterizacion/confirmar", headers=h(w.estudiante_user)).status_code == 403
    assert client.patch(f"{u(w, w.otro_estudiante)}/caracterizacion/autodescripcion", json={"autodescripcion_estudiante": "x"}, headers=h(w.estudiante_user)).status_code == 403
    _ = db


def test_campos_sensibles_cifrados_en_reposo(client, db, world):
    fill_and_confirm_f1(client, world.bienestar, world.estudiante.id)
    for tabla, col in (("dato_comunicacion", "descripcion"), ("dato_sensorial", "descripcion_experiencia"),
                       ("caracterizacion", "resumen_ejecutivo"), ("historia_academica", "trayectoria_escolar")):
        raw = db.execute(text(f"SELECT {col} FROM {tabla} WHERE {col} IS NOT NULL")).scalars().first()
        assert raw and raw.startswith("v1:"), tabla


def test_matriz_f1_f2(client, db, world):
    w = world
    fill_and_confirm_f1(client, w.bienestar, w.estudiante.id)
    url = f"{u(w)}/caracterizacion"
    # lectura: Bienestar, Coordinador de su programa, el propio estudiante
    for ok in (w.bienestar, w.coordinador, w.estudiante_user):
        assert client.get(url, headers=h(ok)).status_code == 200, ok.rol
    # DOCENTE NUNCA, ni Admin, ni otro estudiante, ni coordinador de otro programa, ni familiar sin autorización
    for no in (w.docente, w.admin, w.otro_estudiante_user, w.coordinador_otro, w.familiar):
        assert client.get(url, headers=h(no)).status_code == 403, no.rol
        assert client.get(f"{u(w)}/fortalezas", headers=h(no)).status_code == 403, no.rol
    # Coordinador solo lectura
    assert client.patch(f"{url}/resumen", json={"resumen_ejecutivo": "x"}, headers=h(w.coordinador)).status_code == 403
    # Familiar con autorización lee
    authorize_familiar(db, w.estudiante, w.familiar, ["CARACTERIZACION"])
    assert client.get(url, headers=h(w.familiar)).status_code == 200
    assert client.patch(f"{url}/resumen", json={"resumen_ejecutivo": "x"}, headers=h(w.familiar)).status_code == 403
    # auditoría de lecturas
    db.expire_all()
    quienes = {a.actor_rol for a in db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "ACCESO_CARACTERIZACION"))}
    assert {"BIENESTAR", "COORDINADOR", "ESTUDIANTE", "FAMILIAR"} <= quienes


def test_f2_secciones_confirmacion_y_voz(client, world):
    w = world
    f2 = f"{u(w)}/fortalezas"
    for sec, body in F2.items():
        r = client.patch(f"{f2}/{sec}", json=body, headers=h(w.bienestar if sec != "metas" else w.estudiante_user))
        assert r.status_code == 200, (sec, r.text)
    # idempotente
    r = client.patch(f"{f2}/fortalezas", json=F2["fortalezas"], headers=h(w.bienestar))
    assert len(client.get(f2, headers=h(w.bienestar)).json()["fortalezas"]) == 1
    client.patch(f"{f2}/narrativas", json={"narrativa_fortalezas": "Memoria detallada."}, headers=h(w.bienestar))
    prog = client.get(f"{f2}/progreso", headers=h(w.bienestar)).json()
    assert prog["porcentaje"] == 100 and prog["puede_confirmar"]
    assert any(b["titulo"] == "Metas" for b in client.get(f"{f2}/vista-previa", headers=h(w.bienestar)).json()["bloques"])
    assert client.post(f"{f2}/confirmar", headers=h(w.bienestar)).json()["estado"] == "COMPLETA"
    # editar tras confirmar => versión 2
    client.patch(f"{f2}/intereses", json={"items": [{"nombre_interes": "Farmacología", "descripcion": "Le interesan los fármacos."}]}, headers=h(w.bienestar))
    ver = client.get(f2, headers=h(w.bienestar)).json()
    assert ver["version"] == 2 and ver["estado"] == "INCOMPLETA" and len(ver["intereses"]) == 2 and len(ver["fortalezas"]) == 1
    assert client.get(f2, headers=h(w.docente)).status_code == 403
