"""Slice A: usuarios, programas, asignaturas, Vía 1, Vía 2 (solicitudes) y Vía 3 (CSV)."""

from __future__ import annotations

import pytest

import io

from sqlalchemy import select

from app.models import (
    AsignacionDocente,
    EmailOutbox,
    Estudiante,
    LogAuditoria,
    ProgramaAcademico,
    SolicitudIngreso,
    Usuario,
)
from app.models.enums import EstadoUsuario, Rol
from tests._slice_a_helpers import set_domains, token_from_outbox
from tests.factories import make_user


# ----------------------------------------------------------------------------- cuentas
@pytest.mark.usefixtures("con_correo")
def test_admin_crea_docente_con_invitacion_72h(client, db, world, auth):
    r = client.post("/api/v1/usuarios", headers=auth(world.admin), json={
        "email": "Nuevo.Docente@example.com", "nombre_completo": "Nuevo Docente", "rol": "DOCENTE",
        "programa_id": world.programa.id, "especialidad": "Anatomía"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "PENDIENTE_ACTIVACION" and body["email"] == "nuevo.docente@example.com"
    assert body["programa_id"] == world.programa.id and body["invitacion_pendiente"] is True
    token = token_from_outbox(db, "nuevo.docente@example.com")
    ok = client.post("/api/v1/auth/activate", json={"token": token, "password": "Clave12345!"})
    assert ok.status_code == 200 and ok.json()["estado"] == "ACTIVO"
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "USUARIO_CREADO", LogAuditoria.actor_id == world.admin.id))


def test_crear_usuario_validaciones_y_roles(client, db, world, auth):
    h = auth(world.admin)
    base = {"email": "a@example.com", "nombre_completo": "Alguien Más", "rol": "BIENESTAR"}
    assert client.post("/api/v1/usuarios", headers=h, json=base).status_code == 201
    dup = client.post("/api/v1/usuarios", headers=h, json=base)
    assert dup.status_code == 409 and dup.json()["code"] == "EMAIL_DUPLICADO"
    est = client.post("/api/v1/usuarios", headers=h, json={**base, "email": "b@example.com", "rol": "ESTUDIANTE"})
    assert est.status_code == 422
    assert client.post("/api/v1/usuarios", headers=h, json={**base, "email": "c@example.com", "programa_id": 9999,
                                                           "rol": "DOCENTE"}).json()["code"] == "PROGRAMA_INVALIDO"
    # coordinador con varios programas
    r = client.post("/api/v1/usuarios", headers=h, json={**base, "email": "coo@example.com", "rol": "COORDINADOR",
                                                        "programas_ids": [world.programa.id, world.otro_programa.id]})
    assert r.status_code == 201 and sorted(r.json()["programas_ids"]) == sorted([world.programa.id, world.otro_programa.id])


def test_bienestar_solo_gestiona_docentes(client, world, auth):
    h = auth(world.bienestar)
    assert client.post("/api/v1/usuarios", headers=h, json={"email": "d@example.com", "nombre_completo": "Doc Nuevo",
                                                          "rol": "DOCENTE"}).status_code == 201
    assert client.post("/api/v1/usuarios", headers=h, json={"email": "c@example.com", "nombre_completo": "Coord Nuevo",
                                                          "rol": "COORDINADOR"}).status_code == 403
    lista = client.get("/api/v1/usuarios", headers=h).json()
    assert lista["items"] and all(u["rol"] == "DOCENTE" for u in lista["items"])
    assert client.get("/api/v1/usuarios?rol=ADMIN", headers=h).status_code == 403
    assert client.get(f"/api/v1/usuarios/{world.admin.id}", headers=h).status_code == 403
    assert client.post(f"/api/v1/usuarios/{world.docente.id}/desactivar", headers=h).status_code == 403


def test_rbac_usuarios_otros_roles(client, world, auth):
    for u in (world.docente, world.estudiante_user, world.coordinador, world.familiar):
        assert client.get("/api/v1/usuarios", headers=auth(u)).status_code == 403
    assert client.get("/api/v1/usuarios").status_code == 401


def test_listar_filtros_y_paginacion(client, world, auth):
    h = auth(world.admin)
    r = client.get("/api/v1/usuarios?rol=DOCENTE&page_size=1", headers=h).json()
    assert r["total"] == 2 and len(r["items"]) == 1 and r["page_size"] == 1
    assert client.get(f"/api/v1/usuarios?q={world.docente.email}", headers=h).json()["total"] == 1
    assert client.get("/api/v1/usuarios?estado=SUSPENDIDO", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/usuarios?rol=DOCENTE&programa_id={world.otro_programa.id}", headers=h).json()["total"] == 0


def test_editar_desactivar_reactivar(client, db, world, auth):
    h = auth(world.admin)
    r = client.patch(f"/api/v1/usuarios/{world.docente.id}", headers=h, json={"nombre_completo": "Docente Editado", "telefono": "3001234567"})
    assert r.status_code == 200 and r.json()["nombre_completo"] == "Docente Editado"
    assert client.patch(f"/api/v1/usuarios/{world.docente.id}", headers=h, json={"email": world.bienestar.email}).status_code == 409
    d = client.post(f"/api/v1/usuarios/{world.docente.id}/desactivar", headers=h, json={"motivo": "Fin de contrato"})
    assert d.status_code == 200 and d.json()["estado"] == "INACTIVO"
    assert client.post(f"/api/v1/usuarios/{world.docente.id}/desactivar", headers=h).json()["code"] == "CUENTA_YA_INACTIVA"
    assert client.get("/api/v1/auth/me", headers=auth(world.docente)).json()["code"] == "CUENTA_INACTIVA"
    re_ = client.post(f"/api/v1/usuarios/{world.docente.id}/reactivar", headers=h)
    assert re_.status_code == 200 and re_.json()["estado"] == "ACTIVO"
    assert client.post(f"/api/v1/usuarios/{world.docente.id}/reactivar", headers=h).status_code == 409
    log = db.scalars(select(LogAuditoria).where(LogAuditoria.accion == "USUARIO_MODIFICADO", LogAuditoria.entidad_id == world.docente.id)).all()
    assert len(log) >= 3


def test_no_autodesactivar_ni_ultimo_admin_y_archivar(client, db, world, auth):
    h = auth(world.admin)
    assert client.post(f"/api/v1/usuarios/{world.admin.id}/desactivar", headers=h).json()["code"] == "AUTO_DESACTIVACION"
    otro = make_user(db, Rol.ADMIN)
    r = client.post(f"/api/v1/usuarios/{world.admin.id}/desactivar", headers=auth(otro))
    assert r.status_code == 200  # hay otro admin activo (el solicitante)
    assert client.post(f"/api/v1/usuarios/{otro.id}/desactivar", headers=auth(otro)).json()["code"] == "AUTO_DESACTIVACION"
    # archivar docente (soft delete): ya no aparece y el correo sigue reservado
    assert client.delete(f"/api/v1/usuarios/{world.docente_otro.id}", headers=auth(otro)).status_code == 204
    assert client.get(f"/api/v1/usuarios/{world.docente_otro.id}", headers=auth(otro)).status_code == 404
    dup = client.post("/api/v1/usuarios", headers=auth(otro), json={"email": world.docente_otro.email, "nombre_completo": "Repetido Doc", "rol": "DOCENTE"})
    assert dup.status_code == 409
    fila = db.scalar(select(Usuario).where(Usuario.id == world.docente_otro.id).execution_options(include_deleted=True))
    assert fila.deleted_at is not None


@pytest.mark.usefixtures("con_correo")
def test_reenviar_invitacion(client, db, world, auth):
    h = auth(world.admin)
    client.post("/api/v1/usuarios", headers=h, json={"email": "inv@example.com", "nombre_completo": "Invitado Docente", "rol": "DOCENTE"})
    t1 = token_from_outbox(db, "inv@example.com")
    r = client.post(f"/api/v1/usuarios/{db.scalar(select(Usuario.id).where(Usuario.email == 'inv@example.com'))}/reenviar-invitacion", headers=h)
    assert r.status_code == 200
    t2 = token_from_outbox(db, "inv@example.com")
    assert t1 != t2
    assert client.post("/api/v1/auth/activate", json={"token": t1, "password": "Clave12345!"}).status_code == 400  # token viejo invalidado
    assert client.post("/api/v1/auth/activate", json={"token": t2, "password": "Clave12345!"}).status_code == 200
    again = client.post(f"/api/v1/usuarios/{world.docente.id}/reenviar-invitacion", headers=h)
    assert again.status_code == 409 and again.json()["code"] == "CUENTA_YA_ACTIVADA"


def test_asignaciones_docente(client, db, world, auth):
    h = auth(world.admin)
    a = client.post("/api/v1/usuarios/asignaturas", headers=h, json={"programa_id": world.programa.id, "codigo": "ENF202", "nombre": "Cuidado del adulto"})
    assert a.status_code == 201
    aid = a.json()["id"]
    r = client.post(f"/api/v1/usuarios/{world.docente_otro.id}/asignaciones", headers=h, json={"asignatura_id": aid, "semestre_academico": "2026-II", "grupo": "A"})
    assert r.status_code == 201 and r.json()["items"][0]["asignatura_codigo"] == "ENF202"
    dup = client.post(f"/api/v1/usuarios/{world.docente_otro.id}/asignaciones", headers=h, json={"asignatura_id": aid, "semestre_academico": "2026-II", "grupo": "A"})
    assert dup.status_code == 409
    asign_id = r.json()["items"][0]["id"]
    assert client.get(f"/api/v1/usuarios/{world.docente_otro.id}", headers=h).json()["asignaciones"]
    # la asignatura en uso no se archiva
    assert client.delete(f"/api/v1/usuarios/asignaturas/{aid}", headers=h).json()["code"] == "ASIGNATURA_EN_USO"
    assert client.delete(f"/api/v1/usuarios/{world.docente_otro.id}/asignaciones/{asign_id}", headers=h).status_code == 204
    assert db.scalar(select(AsignacionDocente).where(AsignacionDocente.id == asign_id)) is None
    assert client.delete(f"/api/v1/usuarios/asignaturas/{aid}", headers=h).status_code == 204
    # estudiante no es docente
    assert client.post(f"/api/v1/usuarios/{world.estudiante_user.id}/asignaciones", headers=h, json={"asignatura_id": aid, "semestre_academico": "2026-II"}).status_code == 422


def test_programas_y_asignaturas_crud(client, world, auth):
    h = auth(world.admin)
    p = client.post("/api/v1/usuarios/programas", headers=h, json={"nombre_programa": "Fisioterapia", "codigo_programa": "FIS", "semestre_practicas": 7})
    assert p.status_code == 201
    pid = p.json()["id"]
    assert client.post("/api/v1/usuarios/programas", headers=h, json={"nombre_programa": "Otra", "codigo_programa": "FIS"}).status_code == 409
    assert client.patch(f"/api/v1/usuarios/programas/{pid}", headers=h, json={"duracion_semestres": 10}).json()["duracion_semestres"] == 10
    assert client.get("/api/v1/usuarios/programas", headers=auth(world.coordinador)).status_code == 200
    assert client.post("/api/v1/usuarios/programas", headers=auth(world.bienestar), json={"nombre_programa": "X", "codigo_programa": "XX"}).status_code == 403
    assert client.delete(f"/api/v1/usuarios/programas/{world.programa.id}", headers=h).json()["code"] == "PROGRAMA_EN_USO"
    assert client.delete(f"/api/v1/usuarios/programas/{pid}", headers=h).status_code == 204
    lst = client.get(f"/api/v1/usuarios/asignaturas?programa_id={world.programa.id}", headers=auth(world.bienestar)).json()
    assert lst["total"] == 1 and lst["items"][0]["codigo"] == "ENF101"


# ----------------------------------------------------------------------------- Vía 1
@pytest.mark.usefixtures("con_correo")
def test_via1_bienestar_crea_estudiante(client, db, world, auth):
    h = auth(world.bienestar)
    body = {"nombre_completo": "Ana Estudiante", "codigo_estudiante": "2026777", "programa_id": world.programa.id,
            "email": "ana@example.com", "consentimiento_verbal_declarado": True}
    r = client.post("/api/v1/usuarios/estudiantes", headers=h, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "PENDIENTE_ACTIVACION" and r.json()["via_ingreso"] == "BIENESTAR"
    assert db.scalar(select(Estudiante).where(Estudiante.codigo_estudiante == "2026777")).via_ingreso == "BIENESTAR"
    tok = token_from_outbox(db, "ana@example.com")
    act = client.post("/api/v1/auth/activate", json={"token": tok, "password": "Clave12345!"})
    assert act.json()["estado"] == "PENDIENTE_CONSENTIMIENTO"
    assert client.post("/api/v1/usuarios/estudiantes", headers=h, json=body).status_code == 409
    sin = {**body, "codigo_estudiante": "2026778", "email": "b@example.com", "consentimiento_verbal_declarado": False}
    assert client.post("/api/v1/usuarios/estudiantes", headers=h, json=sin).status_code == 422
    assert client.post("/api/v1/usuarios/estudiantes", headers=auth(world.docente), json=body).status_code == 403
    aud = db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "ESTUDIANTE_CREADO_VIA1"))
    assert aud and aud.detalle["consentimiento_verbal_declarado"] is True


def test_via1_dominio_institucional(client, world, auth, monkeypatch):
    set_domains(monkeypatch, "unicordoba.edu.co")
    try:
        r = client.post("/api/v1/usuarios/estudiantes", headers=auth(world.bienestar), json={
            "nombre_completo": "Ana Estudiante", "codigo_estudiante": "2026779", "programa_id": world.programa.id,
            "email": "ana@gmail.com", "consentimiento_verbal_declarado": True})
        assert r.status_code == 422 and r.json()["code"] == "CORREO_NO_INSTITUCIONAL"
    finally:
        set_domains(monkeypatch, None)


# ----------------------------------------------------------------------------- Vía 2
SOL = {"codigo_estudiantil": "2026888", "email_institucional": "sol@example.com", "nombre_completo": "Sol Icitante",
       "acepta_aviso_privacidad": True}


@pytest.mark.usefixtures("con_correo")
def test_via2_publica_y_aprobacion(client, db, world, auth):
    r = client.post("/api/v1/solicitudes/publica", json={**SOL, "programa_id": world.programa.id})
    assert r.status_code == 202 and "Bienestar" in r.json()["detail"]
    assert db.query(Usuario).filter_by(email="sol@example.com").first() is None  # no hay cuenta sin aprobación
    # duplicado y código existente: misma respuesta, sin nuevas filas
    r2 = client.post("/api/v1/solicitudes/publica", json=SOL)
    est_codigo = world.estudiante.codigo_estudiante
    r3 = client.post("/api/v1/solicitudes/publica", json={**SOL, "codigo_estudiantil": est_codigo, "email_institucional": "otro@example.com"})
    assert r2.json() == r.json() == r3.json()
    db.expire_all()
    assert db.query(SolicitudIngreso).count() == 1
    # listado: solo Bienestar/Admin
    assert client.get("/api/v1/solicitudes", headers=auth(world.docente)).status_code == 403
    lst = client.get("/api/v1/solicitudes?estado=PENDIENTE", headers=auth(world.bienestar)).json()
    assert lst["total"] == 1 and lst["items"][0]["verificada_directorio"] is False
    sid = lst["items"][0]["id"]
    ap = client.post(f"/api/v1/solicitudes/{sid}/aprobar", headers=auth(world.bienestar))
    assert ap.status_code == 200 and ap.json()["estado"] == "APROBADA" and ap.json()["usuario_creado_id"]
    db.expire_all()
    u = db.query(Usuario).filter_by(email="sol@example.com").one()
    assert u.estado == EstadoUsuario.PENDIENTE_ACTIVACION
    assert db.query(Estudiante).filter_by(usuario_id=u.id).one().via_ingreso == "AUTOIDENTIFICACION"
    assert token_from_outbox(db, "sol@example.com")
    assert client.post(f"/api/v1/solicitudes/{sid}/aprobar", headers=auth(world.bienestar)).json()["code"] == "SOLICITUD_YA_RESUELTA"


def test_via2_rechazo_y_notificacion_a_bienestar(client, db, world, auth):
    client.post("/api/v1/solicitudes/publica", json=SOL)
    from app.models import Notificacion

    db.expire_all()
    assert db.scalar(select(Notificacion).where(Notificacion.usuario_id == world.bienestar.id, Notificacion.tipo == "SOLICITUD_INGRESO_NUEVA"))
    sid = db.scalar(select(SolicitudIngreso.id))
    assert client.post(f"/api/v1/solicitudes/{sid}/rechazar", headers=auth(world.bienestar), json={"motivo": "x"}).status_code == 422
    r = client.post(f"/api/v1/solicitudes/{sid}/rechazar", headers=auth(world.bienestar), json={"motivo": "No figura en matrícula"})
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA"
    mail = db.scalar(select(EmailOutbox).where(EmailOutbox.destinatario_email == "sol@example.com"))
    assert mail and "No figura" not in mail.cuerpo_texto  # el motivo interno no se envía
    assert client.post(f"/api/v1/solicitudes/{sid}/aprobar", headers=auth(world.admin)).status_code == 409


def test_via2_honeypot_privacidad_dominio_y_rate_limit(client, db, world, monkeypatch):
    hp = client.post("/api/v1/solicitudes/publica", json={**SOL, "sitio_web": "http://spam"})
    assert hp.status_code == 202
    db.expire_all()
    assert db.query(SolicitudIngreso).count() == 0
    assert client.post("/api/v1/solicitudes/publica", json={**SOL, "acepta_aviso_privacidad": False}).json()["code"] == "AVISO_PRIVACIDAD_REQUERIDO"
    set_domains(monkeypatch, "unicordoba.edu.co")
    try:
        bad = client.post("/api/v1/solicitudes/publica", json={**SOL, "email_institucional": "x@gmail.com"})
        assert bad.status_code == 422 and bad.json()["code"] == "CORREO_NO_INSTITUCIONAL"
        assert client.post("/api/v1/solicitudes/publica", json={**SOL, "email_institucional": "x@unicordoba.edu.co"}).status_code == 202
    finally:
        set_domains(monkeypatch, None)
    monkeypatch.setenv("SOLICITUDES_RATE_LIMIT_PER_HOUR", "2")
    from app.services.directorio import reset_directory_settings

    reset_directory_settings()
    try:
        codes = [client.post("/api/v1/solicitudes/publica", json={**SOL, "codigo_estudiantil": f"99{i}9{i}9"}).status_code for i in range(4)]
        assert codes[-1] == 429
    finally:
        monkeypatch.delenv("SOLICITUDES_RATE_LIMIT_PER_HOUR")
        reset_directory_settings()


def test_programas_publicos(client, world):
    r = client.get("/api/v1/solicitudes/programas")
    assert r.status_code == 200 and {p["nombre"] for p in r.json()["items"]} == {"Enfermería", "Medicina"}


# ----------------------------------------------------------------------------- Vía 3 (CSV)
CSV_OK = "nombre_completo,codigo_estudiante,correo_institucional,programa\nLuis Pérez,2026001,luis@example.com,{c}\nMaría Gómez,2026002,maria@example.com,Enfermería\n"


def _csv(content: str, name: str = "est.csv"):
    return {"archivo": (name, io.BytesIO(content.encode("utf-8")), "text/csv")}


def test_csv_dry_run_errores_por_fila(client, db, world, auth):
    h = auth(world.admin)
    bad = ("nombre,codigo,correo,programa\nAna,2026010,ana@example.com,ENF-NO\n,2026011,nadie,Medicina\n"
           f"Dup,2026010,dup@example.com,{world.programa.codigo_programa}\n")
    r = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=true", headers=h, files=_csv(bad))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["dry_run"] is True and j["creados"] == 0 and j["con_errores"] == 3
    campos = {(e["fila"], e["campo"]) for e in j["errores"]}
    assert (2, "programa") in campos and (3, "nombre_completo") in campos and (3, "correo_institucional") in campos
    assert (4, "codigo_estudiante") in campos
    db.expire_all()
    assert db.query(Estudiante).filter(Estudiante.codigo_estudiante.like("20260%")).count() == 0


@pytest.mark.usefixtures("con_correo")
def test_csv_importa_idempotente_y_estados(client, db, world, auth):
    h = auth(world.admin)
    csv_text = CSV_OK.format(c=world.programa.codigo_programa)
    dry = client.post("/api/v1/admin/estudiantes/importar-csv", headers=h, files=_csv(csv_text)).json()  # dry_run por defecto
    assert dry["dry_run"] is True and dry["nuevas"] == 2
    r = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=false", headers=h, files=_csv(csv_text))
    assert r.status_code == 200 and r.json()["creados"] == 2
    db.expire_all()
    u = db.query(Usuario).filter_by(email="luis@example.com").one()
    assert u.estado == EstadoUsuario.PENDIENTE_CONSENTIMIENTO and u.password_hash is None
    assert db.query(Estudiante).filter_by(usuario_id=u.id).one().via_ingreso == "MATRICULA_CSV"
    mail = db.scalar(select(EmailOutbox).where(EmailOutbox.destinatario_email == "luis@example.com"))
    assert "F0" in mail.cuerpo_texto and "consentimiento" in mail.cuerpo_texto.lower() and "token=" in mail.cuerpo_texto
    again = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=false", headers=h, files=_csv(csv_text)).json()
    assert again["creados"] == 0 and again["ya_existentes"] == 2
    # conflicto: mismo código con otro correo
    conflict = ("nombre_completo;codigo_estudiante;correo_institucional;programa\n"
                f"Luis;2026001;otro@example.com;{world.programa.codigo_programa}\n")
    c = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=true", headers=h, files=_csv(conflict)).json()
    assert c["con_errores"] == 1 and "otro correo" in c["errores"][0]["mensaje"]


@pytest.mark.usefixtures("con_correo")
def test_csv_con_errores_no_importa_salvo_omitir(client, db, world, auth):
    h = auth(world.admin)
    mixto = (f"nombre_completo,codigo_estudiante,correo_institucional,programa\nBien,2026020,bien@example.com,{world.programa.codigo_programa}\n"
             "Mal,2026021,mal,Medicina\n")
    r = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=false", headers=h, files=_csv(mixto))
    assert r.status_code == 422 and r.json()["code"] == "CSV_CON_ERRORES" and r.json()["errores"]
    db.expire_all()
    assert db.query(Usuario).filter_by(email="bien@example.com").first() is None
    ok = client.post("/api/v1/admin/estudiantes/importar-csv?dry_run=false&omitir_errores=true", headers=h, files=_csv(mixto))
    assert ok.status_code == 200 and ok.json()["creados"] == 1


def test_csv_plantilla_permisos_y_columnas(client, world, auth):
    r = client.get("/api/v1/admin/estudiantes/plantilla-csv", headers=auth(world.admin))
    assert r.status_code == 200 and "codigo_estudiante" in r.text and "text/csv" in r.headers["content-type"]
    assert client.get("/api/v1/admin/estudiantes/plantilla-csv", headers=auth(world.bienestar)).status_code == 403
    assert client.post("/api/v1/admin/estudiantes/importar-csv", headers=auth(world.bienestar), files=_csv("a,b\n1,2\n")).status_code == 403
    faltan = client.post("/api/v1/admin/estudiantes/importar-csv", headers=auth(world.admin), files=_csv("nombre,codigo\nA,1\n"))
    assert faltan.status_code == 422 and faltan.json()["code"] == "CSV_COLUMNAS_FALTANTES"
    vacio = client.post("/api/v1/admin/estudiantes/importar-csv", headers=auth(world.admin), files=_csv("# solo comentarios\n"))
    assert vacio.json()["code"] == "CSV_VACIO"


def test_programa_modelo_fixture_sanity(world, db):
    assert db.get(ProgramaAcademico, world.programa.id)
