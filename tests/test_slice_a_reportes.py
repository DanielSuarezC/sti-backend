"""Slice A: reportes M9 (agregados, k-anonimato, alcance por programa) y exportación."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    CasoCbr,
    EstrategiaDua,
    EstrategiaDuaCatalogo,
    LogAuditoria,
    Permanencia,
    Progresion,
    RespuestaAmbiente,
    TrayectoriaAcademica,
)
from app.models.enums import EstadoPlanEnum, Semaforo, TipoAmbientalAjuste
from app.services.reports import Supresor
from tests.factories import make_estudiante, make_plan_with_ajuste

API = "/api/v1"


def _cohorte(db, world, n, *, programa=None, continuan=None, estado=EstadoPlanEnum.IMPLEMENTACION):
    """n estudiantes ficticios con plan vigente, ajuste (ambiente), semáforo y trayectoria."""
    programa = programa or world.programa
    out = []
    for i in range(n):
        u, est = make_estudiante(db, programa)
        plan, ajuste = make_plan_with_ajuste(db, est, world.bienestar, estado=estado)
        plan.semaforo_actual = Semaforo.VERDE if i % 3 else Semaforo.AMARILLO
        db.add(RespuestaAmbiente(ajuste_id=ajuste.id, tipo_ambiental_ajuste=TipoAmbientalAjuste.UBICACION_ESPECIFICA))
        t = TrayectoriaAcademica(estudiante_id=est.id, semestre_academico="2026-II", fecha_inicio_semestre=date(2026, 8, 3),
                                 promedio_academico=4.0)
        db.add(t)
        db.flush()
        db.add(Permanencia(trayectoria_id=t.id, continua_matriculado=(continuan is None or i < continuan)))
        db.add(Progresion(trayectoria_id=t.id, avance_plan_estudios_porcentaje=20 + i))
        db.commit()
        out.append((u, est, plan, ajuste))
    return out


# ----------------------------------------------------------------------------- k-anonimato (unidad)
def test_supresor_celdas_y_complementaria():
    s = Supresor(3)
    assert s.cell(0) == 0 and s.cell(1) is None and s.cell(2) is None and s.cell(3) == 3
    assert Supresor(3).distribucion({"A": 5, "B": 1}) == {"A": None, "B": None}  # no se deduce B restando
    assert Supresor(3).distribucion({"A": 4, "B": 1, "C": 3}) == {"A": 4, "B": None, "C": None}
    assert Supresor(3).distribucion({"A": 3, "B": 3, "C": 0}) == {"A": 3, "B": 3, "C": 0}
    assert Supresor(3).distribucion({"A": 1, "B": 1}) == {"A": None, "B": None}
    # multi-pertenencia (no es partición): solo supresión primaria
    assert Supresor(3).distribucion({"A": 5, "B": 1}, particion=False) == {"A": 5, "B": None}


# ----------------------------------------------------------------------------- dashboard
def test_dashboard_suprime_n_menor_que_3(client, db, world, auth):
    _cohorte(db, world, 2)
    j = client.get(f"{API}/reportes/dashboard", headers=auth(world.coordinador)).json()
    fila = j["programas"][0]
    assert fila["planes_activos"] is None and j["totales"]["planes_activos"] is None
    assert all(v is None for v in fila["semaforo"].values()) and fila["tipos_barrera"] == {}
    assert j["celdas_suprimidas"] >= 1 and j["k_minimo"] == 3 and "menos de 3" in j["nota_privacidad"]


def test_dashboard_muestra_agregados_con_n_suficiente(client, db, world, auth):
    _cohorte(db, world, 4, continuan=3)
    j = client.get(f"{API}/reportes/dashboard", headers=auth(world.coordinador)).json()
    fila = j["programas"][0]
    assert fila["planes_activos"] == 4
    # 4 planes: 3 verdes (i=1,2,3) y 1 amarillo (i=0): el amarillo (n=1) y la complementaria se ocultan
    assert fila["semaforo"]["AMARILLO"] is None and fila["semaforo"]["ROJO"] == 0
    assert fila["tipos_barrera"] == {"SENSORIAL": 4}
    assert fila["permanencia"]["continuan"] is None and fila["permanencia"]["tasa_permanencia_pct"] is None  # 3 + 1 oculto
    _cohorte(db, world, 3, estado=EstadoPlanEnum.SEGUIMIENTO)
    j2 = client.get(f"{API}/reportes/dashboard", headers=auth(world.admin)).json()
    assert j2["programas"][0]["planes_activos"] == 7 and j2["totales"]["planes_activos"] == 7
    assert j2["programas"][1]["planes_activos"] == 0  # Medicina: sin casos (cero no se oculta)


def test_dashboard_no_contiene_identificadores(client, db, world, auth):
    datos = _cohorte(db, world, 4)
    texto = client.get(f"{API}/reportes/dashboard", headers=auth(world.admin)).text
    for u, est, _p, _a in datos:
        assert u.email not in texto and u.nombre_completo not in texto and est.codigo_estudiante not in texto
    for clave in ("estudiante_id", "email", "nombre_completo", "codigo_estudiante"):
        assert clave not in texto


def test_coordinador_solo_ve_su_programa(client, db, world, auth):
    _cohorte(db, world, 3)
    _cohorte(db, world, 3, programa=world.otro_programa)
    mio = client.get(f"{API}/reportes/dashboard", headers=auth(world.coordinador)).json()
    assert [p["programa_id"] for p in mio["programas"]] == [world.programa.id]
    assert mio["alcance"]["programas"] == [{"id": world.programa.id, "nombre": "Enfermería"}]
    ajeno = client.get(f"{API}/reportes/dashboard?programa_id={world.otro_programa.id}", headers=auth(world.coordinador))
    assert ajeno.status_code == 403 and ajeno.json()["code"] == "PROGRAMA_FUERA_DE_ALCANCE"
    for ruta in ("trayectorias", "ajustes-frecuentes", "efectividad-dua"):
        assert client.get(f"{API}/reportes/{ruta}?programa_id={world.otro_programa.id}", headers=auth(world.coordinador)).status_code == 403
    assert client.get(f"{API}/reportes/dashboard?programa_id={world.otro_programa.id}", headers=auth(world.coordinador_otro)).status_code == 200
    todos = client.get(f"{API}/reportes/dashboard", headers=auth(world.admin)).json()
    assert len(todos["programas"]) == 2 and todos["totales"]["planes_activos"] == 6
    assert client.get(f"{API}/reportes/alcance", headers=auth(world.coordinador_otro)).json()["programas"][0]["id"] == world.otro_programa.id


def test_reportes_rbac(client, world, auth):
    for u in (world.bienestar, world.docente, world.estudiante_user, world.familiar):
        for ruta in ("dashboard", "trayectorias", "ajustes-frecuentes", "efectividad-dua", "uso", "dashboard/export", "referencias"):
            assert client.get(f"{API}/reportes/{ruta}", headers=auth(u)).status_code in (403, 404), ruta
    assert client.get(f"{API}/reportes/dashboard").status_code == 401
    assert client.get(f"{API}/reportes/uso", headers=auth(world.coordinador)).status_code == 403


def test_k_configurable_no_baja_de_3(client, db, world, auth):
    _cohorte(db, world, 4)
    h = auth(world.admin)
    assert client.put(f"{API}/calendario/parametros/reportes_k_minimo", headers=h, json={"valor": 5}).status_code == 200
    j = client.get(f"{API}/reportes/dashboard", headers=h).json()
    assert j["k_minimo"] == 5 and j["programas"][0]["planes_activos"] is None  # 4 < 5
    assert client.put(f"{API}/calendario/parametros/reportes_k_minimo", headers=h, json={"valor": 1}).status_code == 422


# ----------------------------------------------------------------------------- trayectorias
def test_trayectorias_vs_referencia(client, db, world, auth):
    _cohorte(db, world, 4, continuan=4)
    h = auth(world.admin)
    ref = client.put(f"{API}/reportes/referencias/{world.programa.id}", headers=h,
                     json={"permanencia_pct": 80, "avance_promedio_pct": 20, "promedio_academico": 3.8, "fuente": "SIGAA 2026-I"})
    assert ref.status_code == 200
    assert client.put(f"{API}/reportes/referencias/{world.programa.id}", headers=auth(world.coordinador), json={}).status_code == 403
    assert client.put(f"{API}/reportes/referencias/9999", headers=h, json={}).status_code == 404
    assert client.put(f"{API}/reportes/referencias/{world.programa.id}", headers=h, json={"permanencia_pct": 120}).status_code == 422
    j = client.get(f"{API}/reportes/trayectorias?programa_id={world.programa.id}", headers=auth(world.coordinador)).json()
    ind = j["programas"][0]["indicadores"]
    assert ind["permanencia_pct"] == {"cohorte_tea": 100.0, "referencia_programa": 80.0, "diferencia": 20.0}
    assert ind["avance_promedio_pct"]["cohorte_tea"] == 21.5 and ind["promedio_academico"]["diferencia"] == 0.2
    assert j["programas"][0]["referencia_fuente"] == "SIGAA 2026-I"
    # parámetro de referencia en la consulta (sobrescribe solo esta vez)
    o = client.get(f"{API}/reportes/trayectorias?programa_id={world.programa.id}&ref_permanencia=95", headers=h).json()
    assert o["programas"][0]["indicadores"]["permanencia_pct"]["diferencia"] == 5.0
    assert client.get(f"{API}/reportes/referencias", headers=auth(world.coordinador)).json()["items"][0]["permanencia_pct"] == 80


def test_trayectorias_suprime_con_pocos_casos(client, db, world, auth):
    _cohorte(db, world, 2)
    j = client.get(f"{API}/reportes/trayectorias", headers=auth(world.coordinador)).json()["programas"][0]
    assert j["estudiantes_con_trayectoria"] is None
    assert all(v["cohorte_tea"] is None for v in j["indicadores"].values())


# ----------------------------------------------------------------------------- ajustes y DUA
def test_ajustes_frecuentes_con_supresion(client, db, world, auth):
    _cohorte(db, world, 3)
    _cohorte(db, world, 1)
    j = client.get(f"{API}/reportes/ajustes-frecuentes", headers=auth(world.coordinador)).json()
    assert j["categorias"] == [{"categoria": "AMBIENTE", "estudiantes": 4, "ajustes": 4}]
    assert j["ajustes_especificos"][0]["tipo"] == "UBICACION_ESPECIFICA" and j["ajustes_especificos"][0]["estudiantes"] == 4
    solo2 = client.get(f"{API}/reportes/ajustes-frecuentes?programa_id={world.otro_programa.id}", headers=auth(world.admin)).json()
    assert solo2["categorias"] == [] and solo2["celdas_suprimidas"] == 0


def test_efectividad_dua(client, db, world, auth):
    datos = _cohorte(db, world, 3)
    e = EstrategiaDuaCatalogo(codigo="T-1", nombre="Estrategia T", descripcion_pedagogica="Descripción de prueba",
                              principio="PARTICIPACION", pauta=7, escenarios=["AULA"], tipos_barrera=["SENSORIAL"])
    raro = EstrategiaDuaCatalogo(codigo="T-2", nombre="Estrategia rara", descripcion_pedagogica="Descripción de prueba",
                                 principio="REPRESENTACION", pauta=1, escenarios=[], tipos_barrera=[])
    db.add_all([e, raro])
    db.flush()
    for i, (_u, _est, plan, _a) in enumerate(datos):
        db.add(EstrategiaDua(plan_id=plan.id, nombre_estrategia="x", descripcion="y", dimension_dua="MULTIPLES_MEDIOS_PARTICIPACION",
                             estrategia_catalogo_id=e.id, implementada=i < 2))
        db.add(CasoCbr(estrategia_catalogo_id=e.id, plan_id=plan.id, perfil={"tipos_barrera": ["SENSORIAL"]}, exitoso=i != 0))
    db.add(EstrategiaDua(plan_id=datos[0][2].id, nombre_estrategia="r", descripcion="y", dimension_dua="MULTIPLES_MEDIOS_PRESENTACION",
                         estrategia_catalogo_id=raro.id))
    db.commit()
    j = client.get(f"{API}/reportes/efectividad-dua", headers=auth(world.coordinador)).json()
    assert [x["codigo"] for x in j["estrategias"]] == ["T-1"]  # T-2 tiene 1 estudiante: oculta
    t1 = j["estrategias"][0]
    assert t1["estudiantes"] == 3 and t1["tasa_implementacion_pct"] == 66.7 and t1["tasa_efectividad_pct"] == 66.7
    assert j["estrategias_ocultas"] == 1
    assert {p["principio"]: p["estudiantes"] for p in j["por_principio"]} == {"PARTICIPACION": 3, "REPRESENTACION": None}


def test_uso_del_sistema_admin(client, db, world, auth):
    _cohorte(db, world, 3)
    j = client.get(f"{API}/reportes/uso", headers=auth(world.admin)).json()
    assert j["usuarios_por_rol_estado"]["ADMIN"]["ACTIVO"] >= 1
    assert j["usuarios_por_rol_estado"]["FAMILIAR"]["ACTIVO"] is None  # 1 familiar: oculto
    assert j["planes_por_semestre"][0]["planes_generados"] == 3
    assert "inicios_de_sesion" in j["actividad"]
    assert client.get(f"{API}/reportes/uso?desde=2026-01-01&hasta=2026-02-01", headers=auth(world.admin)).status_code == 200


# ----------------------------------------------------------------------------- exportación
@pytest.mark.parametrize("tipo", ["dashboard", "trayectorias", "ajustes-frecuentes", "efectividad-dua", "uso"])
def test_exportar_xlsx(client, db, world, auth, tipo):
    from io import BytesIO

    from openpyxl import load_workbook

    _cohorte(db, world, 3)
    r = client.get(f"{API}/reportes/{tipo}/export?formato=xlsx", headers=auth(world.admin))
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and r.content[:2] == b"PK"
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames[0] == "Resumen" and len(wb.sheetnames) >= 2
    assert db.scalar(select(LogAuditoria).where(LogAuditoria.accion == "EXPORTACION_SOLICITADA", LogAuditoria.entidad == "reporte"))


def test_exportar_pdf_o_html_degradado_y_permisos(client, db, world, auth):
    _cohorte(db, world, 3)
    r = client.get(f"{API}/reportes/dashboard/export?formato=pdf", headers=auth(world.coordinador))
    assert r.status_code == 200
    if r.headers["content-type"].startswith("application/pdf"):
        assert r.content[:4] == b"%PDF"
    else:  # WeasyPrint sin librerías nativas: HTML imprimible con aviso
        assert "text/html" in r.headers["content-type"] and r.headers["X-Export-Degradado"] == "html"
        assert "Dashboard de inclusión" in r.text and "menos de 3" in r.text
    assert client.get(f"{API}/reportes/dashboard/export?formato=doc", headers=auth(world.admin)).status_code == 422
    assert client.get(f"{API}/reportes/inventado/export", headers=auth(world.admin)).status_code == 404
    assert client.get(f"{API}/reportes/dashboard/export?programa_id={world.otro_programa.id}", headers=auth(world.coordinador)).status_code == 403
    assert client.get(f"{API}/reportes/uso/export", headers=auth(world.coordinador)).status_code == 403
    assert client.get(f"{API}/reportes/dashboard/export", headers=auth(world.docente)).status_code == 403


def test_export_html_no_tiene_identificadores(world, db):
    from app.services import reports

    datos = _cohorte(db, world, 3)
    d = reports.dashboard(db, world.admin)
    html = reports.to_html("dashboard", d)
    assert json.dumps(d) and all(u.email not in html and est.codigo_estudiante not in html for u, est, _p, _a in datos)
