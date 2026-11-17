"""F0 (firma, hash, copia por correo, revocación) y ARCO (solicitudes, plazos, exportación)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.data import f0_texto
from app.models import Estudiante, LogAuditoria, Usuario
from app.models.caracterizacion import Caracterizacion
from app.models.consentimiento import Consentimiento
from app.models.enums import EstadoConsentimiento, EstadoUsuario
from app.models.sistema import EmailOutbox
from app.models.slice_b import ConsentimientoDetalle
from app.services.b_common import add_business_days
from tests.factories import build_world, make_estudiante
from tests.slice_b_helpers import aq10_answers, f0_body, h

API = "/api/v1"


def _pending(db, world):
    return make_estudiante(db, world.programa, consent=False, nombre="Ana Maria Lopez Perez")


def test_texto_publico_versionado_con_revision_juridica(client):
    r = client.get(f"{API}/consentimiento/texto")
    assert r.status_code == 200
    j = r.json()
    assert j["version_texto"] == f0_texto.VERSION and j["texto_hash"] == f0_texto.texto_hash()
    assert j["revision_juridica_pendiente"] is True
    ids = {s["id"] for s in j["secciones"]}
    assert {"proposito", "datos", "quien_accede", "proteccion", "derechos", "retiro"} <= ids
    assert [a["clave"] for a in j["aceptaciones"]] == ["acepta_tratamiento_general", "acepta_datos_sensibles_salud", "acepta_compartir_ajustes_docentes"]


def test_firma_estudiante_activa_cuenta_registra_hash_ip_y_envia_copia(client, db, world):
    u, est = _pending(db, world)
    assert client.get(f"{API}/consentimiento/mio", headers=h(u)).json()["estado"] == "PENDIENTE"
    # sin F0 el resto de la API le responde CONSENTIMIENTO_REQUERIDO, pero el F0 sí funciona
    r = client.get(f"{API}/estudiantes/{est.id}/caracterizacion", headers=h(u))
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"
    r = client.post(f"{API}/consentimiento/firmar", json=f0_body("ana lopez perez"), headers={**h(u), "user-agent": "pytest-ua"})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["firmado"] and j["modalidad"] == "AUTONOMA" and j["copia_enviada_at"]
    db.expire_all()
    c = db.scalar(select(Consentimiento).where(Consentimiento.estudiante_id == est.id))
    assert c.texto_hash == f0_texto.texto_hash() and c.user_agent == "pytest-ua" and c.ip and len(c.firma_hash) == 64
    assert db.get(Usuario, u.id).estado == EstadoUsuario.ACTIVO
    d = db.scalar(select(ConsentimientoDetalle).where(ConsentimientoDetalle.consentimiento_id == c.id))
    assert d.acepta_compartir_ajustes_docentes and d.nombre_firmante == "ana lopez perez"
    mail = db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "CONSENTIMIENTO_COPIA"))
    assert mail and mail.destinatario_email == u.email and f0_texto.texto_hash() in mail.cuerpo_texto
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "CONSENTIMIENTO_FIRMADO"))
    # ya puede usar el resto
    assert client.get(f"{API}/estudiantes/{est.id}/caracterizacion", headers=h(u)).status_code == 200
    # doble firma: 409
    r = client.post(f"{API}/consentimiento/firmar", json=f0_body("ana lopez perez"), headers=h(u))
    assert r.status_code == 409 and r.json()["code"] == "CONSENTIMIENTO_YA_FIRMADO"


def test_firma_validaciones(client, db, world):
    u, est = _pending(db, world)
    base = f0_body("Ana Lopez")
    r = client.post(f"{API}/consentimiento/firmar", json={**base, "acepta_datos_sensibles_salud": False}, headers=h(u))
    assert r.status_code == 422 and r.json()["code"] == "ACEPTACION_REQUERIDA"
    r = client.post(f"{API}/consentimiento/firmar", json={**base, "nombre_firmante": "Pedro Gomez"}, headers=h(u))
    assert r.status_code == 422 and r.json()["code"] == "NOMBRE_NO_COINCIDE"
    r = client.post(f"{API}/consentimiento/firmar", json={**base, "texto_hash": "0" * 64}, headers=h(u))
    assert r.status_code == 409 and r.json()["code"] == "TEXTO_DESACTUALIZADO"
    # tercera aceptación puede ser falsa
    r = client.post(f"{API}/consentimiento/firmar", json={**base, "acepta_compartir_ajustes_docentes": False}, headers=h(u))
    assert r.status_code == 201 and r.json()["acepta_compartir_ajustes_docentes"] is False
    # otros roles no firman por su cuenta
    r = client.post(f"{API}/consentimiento/firmar", json=base, headers=h(world.docente))
    assert r.status_code == 403


def test_firma_asistida_por_bienestar(client, db, world):
    u, est = _pending(db, world)
    r = client.post(f"{API}/consentimiento/firmar", json=f0_body("Ana Maria Lopez", estudiante_id=est.id), headers=h(world.bienestar))
    assert r.status_code == 201, r.text
    assert r.json()["modalidad"] == "ASISTIDA_BIENESTAR" and r.json()["asistido_por_id"] == world.bienestar.id
    r = client.get(f"{API}/consentimiento/{est.id}", headers=h(world.bienestar))
    assert r.status_code == 200 and r.json()["firmado"] is True


def test_estado_de_un_estudiante_solo_bienestar_admin(client, world):
    est = world.estudiante.id
    assert client.get(f"{API}/consentimiento/{est}", headers=h(world.bienestar)).status_code == 200
    for u in (world.docente, world.coordinador, world.estudiante_user, world.familiar):
        assert client.get(f"{API}/consentimiento/{est}", headers=h(u)).status_code == 403


def test_revocacion_inactiva_archiva_notifica_y_audita(client, db, world):
    w = world
    r = client.post(f"{API}/estudiantes/{w.estudiante.id}/aq10", json={"respuestas": aq10_answers(10)}, headers=h(w.estudiante_user))
    assert r.status_code == 201, r.text
    assert db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == w.estudiante.id))
    r = client.post(f"{API}/consentimiento/revocar", json={"confirmar": False}, headers=h(w.estudiante_user))
    assert r.status_code == 422 and r.json()["code"] == "CONFIRMACION_REQUERIDA"
    r = client.post(f"{API}/consentimiento/revocar", json={"confirmar": True, "motivo": "Prefiero no continuar"}, headers=h(w.estudiante_user))
    assert r.status_code == 200, r.text
    assert "respuesta_aq10" in r.json()["datos_archivados"]
    db.expire_all()
    assert db.get(Usuario, w.estudiante_user.id).estado == EstadoUsuario.INACTIVO
    c = db.scalar(select(Consentimiento).where(Consentimiento.estudiante_id == w.estudiante.id))
    assert c.estado == EstadoConsentimiento.REVOCADO and c.revocado_at
    assert db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == w.estudiante.id)) is None  # soft delete
    assert db.scalar(select(Caracterizacion).where(Caracterizacion.estudiante_id == w.estudiante.id).execution_options(include_deleted=True))
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "CONSENTIMIENTO_REVOCADO"))
    assert db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "CONSENTIMIENTO_REVOCADO"))
    # la cuenta queda inactiva: el token ya no sirve
    assert client.get(f"{API}/consentimiento/mio", headers=h(w.estudiante_user)).status_code == 403
    # Bienestar ve el estado
    assert client.get(f"{API}/consentimiento/{w.estudiante.id}", headers=h(w.bienestar)).json()["estado"] == "REVOCADO"


# ------------------------------------------------------------------ ARCO
def test_plazos_en_dias_habiles():
    lunes = date(2026, 11, 16)
    assert add_business_days(lunes, 10) == date(2026, 11, 30)
    assert add_business_days(date(2026, 11, 20), 1) == date(2026, 11, 23)  # viernes -> lunes


def test_arco_flujo_completo(client, db, world):
    w = world
    r = client.post(f"{API}/arco/solicitudes", json={"tipo": "ACCESO", "descripcion": "Quiero conocer mis datos."}, headers=h(w.estudiante_user))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["tramite"] == "CONSULTA" and s["radicado"].startswith("ARCO-")
    assert s["fecha_limite"] == add_business_days(date.today(), 10).isoformat()
    r2 = client.post(f"{API}/arco/solicitudes", json={"tipo": "RECTIFICACION", "descripcion": "Corregir mi autodescripción."}, headers=h(w.estudiante_user))
    assert r2.json()["fecha_limite"] == add_business_days(date.today(), 15).isoformat()
    assert len(client.get(f"{API}/arco/mis-solicitudes", headers=h(w.estudiante_user)).json()["items"]) == 2
    # el otro estudiante no ve ni puede abrir la solicitud
    assert client.get(f"{API}/arco/mis-solicitudes", headers=h(w.otro_estudiante_user)).json()["total"] == 0
    assert client.get(f"{API}/arco/solicitudes/{s['id']}", headers=h(w.otro_estudiante_user)).status_code == 404
    # bandeja: solo Bienestar/Admin
    assert client.get(f"{API}/arco/solicitudes", headers=h(w.docente)).status_code == 403
    assert client.get(f"{API}/arco/solicitudes", headers=h(w.estudiante_user)).status_code == 403
    bandeja = client.get(f"{API}/arco/solicitudes", headers=h(w.bienestar)).json()
    assert bandeja["total"] == 2
    # prórroga una sola vez
    p = client.post(f"{API}/arco/solicitudes/{s['id']}/prorrogar", json={"motivo": "Se requiere consultar con jurídica."}, headers=h(w.bienestar))
    assert p.status_code == 200 and p.json()["prorrogada"] is True
    assert p.json()["fecha_limite"] == add_business_days(date.fromisoformat(s["fecha_limite"]), 5).isoformat()
    assert client.post(f"{API}/arco/solicitudes/{s['id']}/prorrogar", json={"motivo": "Otra vez por favor."}, headers=h(w.bienestar)).json()["code"] == "ARCO_YA_PRORROGADA"
    # cerrar exige respuesta
    r = client.patch(f"{API}/arco/solicitudes/{s['id']}", json={"estado": "RESUELTA"}, headers=h(w.bienestar))
    assert r.status_code == 422 and r.json()["code"] == "RESPUESTA_REQUERIDA"
    r = client.patch(f"{API}/arco/solicitudes/{s['id']}", json={"estado": "RESUELTA", "respuesta": "Le enviamos sus datos."}, headers=h(w.bienestar))
    assert r.status_code == 200 and r.json()["estado"] == "RESUELTA"
    mia = client.get(f"{API}/arco/solicitudes/{s['id']}", headers=h(w.estudiante_user)).json()
    assert mia["respuesta"] == "Le enviamos sus datos."
    assert client.patch(f"{API}/arco/solicitudes/{s['id']}", json={"estado": "EN_TRAMITE"}, headers=h(w.bienestar)).json()["code"] == "ARCO_CERRADA"
    # notificaciones
    assert db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "ARCO_SOLICITUD_NUEVA"))
    assert db.scalar(select(EmailOutbox).where(EmailOutbox.evento == "ARCO_SOLICITUD_RESUELTA"))


def test_exportar_mis_datos_descifrado_y_solo_propios(client, db, world):
    w = world
    client.post(f"{API}/estudiantes/{w.estudiante.id}/aq10", json={"respuestas": aq10_answers(10)}, headers=h(w.estudiante_user))
    client.patch(f"{API}/estudiantes/{w.estudiante.id}/caracterizacion/autodescripcion",
                 json={"autodescripcion_estudiante": "Me concentro en los detalles."}, headers=h(w.estudiante_user))
    r = client.get(f"{API}/arco/exportar-mis-datos", headers=h(w.estudiante_user))
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    j = r.json()
    assert j["cuenta"]["email"] == w.estudiante_user.email
    assert j["datos"]["respuesta_aq10"][0]["puntaje"] == 10  # descifrado
    assert j["datos"]["caracterizacion"][0]["autodescripcion_estudiante"] == "Me concentro en los detalles."
    assert j["consentimientos"] and j["accesos_a_mis_datos"]
    assert "password_hash" not in str(j)
    for u in (w.bienestar, w.docente):
        assert client.get(f"{API}/arco/exportar-mis-datos", headers=h(u)).status_code == 403
    _ = (build_world, Estudiante)
