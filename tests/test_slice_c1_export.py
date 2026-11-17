"""Slice C1: exportación del Plan MAAR-TEA (HTML imprimible, PDF, Word), descarga auditada y expiración."""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Exportacion, LogAuditoria
from app.models.base import utcnow
from app.models.enums import EstadoExportacion
from app.services import exports
from tests.c1_support import Api, firmar_todos, hasta_firmas, seed_insumos


@pytest.fixture()
def plan_firmado(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    plan = hasta_firmas(api, world)
    firmar_todos(api, world, plan["id"])
    return api, plan["id"]


def test_exportar_html_contiene_nombre_y_firmas(client, db, world, plan_firmado):
    api, pid = plan_firmado
    r = api.post(f"/planes/{pid}/exportar", world.bienestar, params={"formato": "html"})
    assert r.status_code == 202, r.text
    ex = r.json()
    assert ex["estado"] == "LISTA" and ex["formato"] == "html" and ex["descarga"]
    assert api.get(f"/exportaciones/{ex['id']}", world.bienestar).json()["estado"] == "LISTA"
    d = api.get(f"/exportaciones/{ex['id']}/descargar", world.bienestar)
    assert d.status_code == 200 and d.headers["content-type"].startswith("text/html")
    html = d.text
    assert world.estudiante_user.nombre_completo in html
    assert 'lang="es"' in html and "Firmas digitales" in html and "Firma válida" in html
    for nombre in (world.estudiante_user, world.bienestar, world.coordinador):
        assert nombre.nombre_completo in html
    assert "Ajustes razonables por categoría" in html and "Matriz de responsabilidades (F7)" in html
    assert "Sin registro de seguimiento" in html  # el semáforo siempre lleva texto
    assert "Ambiente" in html and "Comunicación" in html and "Evaluación" in html
    firma = api.get(f"/planes/{pid}/firmas", world.bienestar).json()["firmas"][0]
    assert firma["hash_corto"] in html
    # descarga auditada
    acciones = [x.accion for x in db.scalars(select(LogAuditoria))]
    assert "EXPORTACION_SOLICITADA" in acciones and "EXPORTACION_DESCARGADA" in acciones
    # notificación al terminar
    from app.models import Notificacion

    assert db.scalar(select(Notificacion.id).where(Notificacion.tipo == "EXPORTACION_LISTA",
                                                  Notificacion.usuario_id == world.bienestar.id)) is not None


def test_pdf_degrada_a_html_si_no_hay_weasyprint(client, db, world, plan_firmado, monkeypatch):
    api, pid = plan_firmado
    monkeypatch.setattr(exports, "pdf_disponible", lambda: False)
    r = api.post(f"/planes/{pid}/exportar", world.estudiante_user, params={"formato": "pdf"})
    assert r.status_code == 202  # nunca 500
    ex = r.json()
    assert ex["formato"] == "html" and ex["formato_solicitado"] == "pdf" and "HTML imprimible" in ex["aviso"]
    assert ex["estado"] == "LISTA"
    assert api.get(f"/exportaciones/{ex['id']}/descargar", world.estudiante_user).status_code == 200


@pytest.mark.skipif(not exports.pdf_disponible(), reason="WeasyPrint no está disponible (en Windows requiere GTK/Pango)")
def test_exportar_pdf(client, db, world, plan_firmado):
    api, pid = plan_firmado
    ex = api.post(f"/planes/{pid}/exportar", world.coordinador, params={"formato": "pdf"}).json()
    assert ex["estado"] == "LISTA" and ex["formato"] == "pdf"
    d = api.get(f"/exportaciones/{ex['id']}/descargar", world.coordinador)
    assert d.content.startswith(b"%PDF") and d.headers["content-type"] == "application/pdf"
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    texto = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(d.content)).pages)
    assert world.estudiante_user.nombre_completo in texto and "Firmas digitales" in texto


def test_exportar_docx(client, db, world, plan_firmado):
    from docx import Document

    api, pid = plan_firmado
    ex = api.post(f"/planes/{pid}/exportar", world.bienestar, params={"formato": "docx"}).json()
    assert ex["estado"] == "LISTA" and ex["formato"] == "docx"
    d = api.get(f"/exportaciones/{ex['id']}/descargar", world.bienestar)
    assert d.status_code == 200 and d.content[:2] == b"PK"
    doc = Document(io.BytesIO(d.content))
    texto = "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
        c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert world.estudiante_user.nombre_completo in texto
    assert "Firmas digitales" in texto and "Firma válida" in texto
    assert world.coordinador.nombre_completo in texto and "Ajustes razonables por categoría" in texto


def test_acceso_a_exportaciones(client, db, world, plan_firmado):
    api, pid = plan_firmado
    ex = api.post(f"/planes/{pid}/exportar", world.estudiante_user, params={"formato": "html"}).json()
    # el docente no exporta (no ve datos del plan completo); otro coordinador/estudiante no descargan
    assert api.post(f"/planes/{pid}/exportar", world.docente, params={"formato": "html"}).status_code == 403
    assert api.post(f"/planes/{pid}/exportar", world.coordinador_otro, params={"formato": "html"}).status_code == 403
    assert api.get(f"/exportaciones/{ex['id']}/descargar", world.coordinador_otro).status_code == 403
    assert api.get(f"/exportaciones/{ex['id']}/descargar", world.otro_estudiante_user).status_code == 403
    assert api.get(f"/exportaciones/{ex['id']}/descargar", world.coordinador).status_code == 200  # puede leer el plan
    assert client.get(f"/api/v1/exportaciones/{ex['id']}/descargar").status_code == 401
    assert api.post(f"/planes/{pid}/exportar", world.estudiante_user, params={"formato": "xls"}).status_code == 422
    assert api.get("/exportaciones/9999", world.bienestar).status_code == 404
    assert api.get(f"/planes/{pid}/exportaciones", world.estudiante_user).json()["total"] == 1


def test_borrador_exportado_lleva_aviso_y_expiracion(client, db, world):
    seed_insumos(db, world)
    api = Api(client)
    from tests.c1_support import crear_plan

    pid = crear_plan(api, world)["id"]
    ex = api.post(f"/planes/{pid}/exportar", world.bienestar, params={"formato": "html"}).json()
    html = api.get(f"/exportaciones/{ex['id']}/descargar", world.bienestar).text
    assert "Borrador sin firmas completas" in html and "Pendiente de firma" in html
    # expiración
    row = db.get(Exportacion, ex["id"])
    row.expira_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert exports.expire_exports(db) == 1
    db.commit()
    assert db.get(Exportacion, ex["id"]).estado == EstadoExportacion.EXPIRADA
    r = api.get(f"/exportaciones/{ex['id']}/descargar", world.bienestar)
    assert r.status_code == 410 and r.json()["code"] == "EXPORTACION_EXPIRADA"
