"""Soporte de las pruebas del slice C1: estado base (barreras, fortaleza, calendario, sugerencia) y atajos HTTP."""

from __future__ import annotations

from datetime import date

from app.models import (
    BarreraIdentificada,
    CalendarioAcademico,
    Facilitador,
    Fortaleza,
    PerfilFortalezas,
)
from app.models.dua import EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import (
    EstadoBarrera,
    EstadoSugerencia,
    PrincipioDua,
    TipoBarrera,
    TipoFacilitador,
    TipoSensorial,
)
from app.models.mapa import BarreraSensorial
from tests.factories import auth_headers

SEMESTRE = "2026-II"


def seed_insumos(db, w, *, calendario: bool = True, sugerencia: bool = True) -> dict:
    """3 barreras persistentes (sensorial auditiva, comunicativa, evaluativa) + fortaleza + facilitador (+ calendario, sugerencia)."""
    est = w.estudiante
    barreras = []
    for tipo, desc in ((TipoBarrera.SENSORIAL, "Ruido de pasillo en el aula"),
                       (TipoBarrera.COMUNICATIVA, "Instrucciones orales rápidas sin soporte escrito"),
                       (TipoBarrera.EVALUATIVA, "Exámenes con tiempo limitado y ambiente ruidoso")):
        b = BarreraIdentificada(estudiante_id=est.id, tipo_barrera=tipo, descripcion_barrera=desc,
                                fecha_identificacion=date(2026, 8, 14), estado=EstadoBarrera.PERSISTENTE,
                                semestre_academico=SEMESTRE, registrada_por_id=w.bienestar.id)
        db.add(b)
        db.flush()
        if tipo == TipoBarrera.SENSORIAL:
            db.add(BarreraSensorial(barrera_id=b.id, tipo_sensorial=TipoSensorial.AUDITIVA))
        barreras.append(b)
    perfil = PerfilFortalezas(estudiante_id=est.id, fecha_elaboracion=date(2026, 8, 12),
                              profesional_responsable_id=w.bienestar.id)
    db.add(perfil)
    db.flush()
    fort = Fortaleza(perfil_fortalezas_id=perfil.id, nombre_fortaleza="Atención al detalle",
                     descripcion_detallada="Detecta errores en instrucciones escritas y procedimientos")
    db.add(fort)
    db.add(Facilitador(estudiante_id=est.id, tipo_facilitador=TipoFacilitador.PEDAGOGICO, nombre_facilitador="Guías escritas del docente",
                       descripcion_detallada="Algunos docentes comparten guías", fecha_identificacion=date(2026, 8, 14)))
    cal = None
    if calendario:
        cal = CalendarioAcademico(semestre_academico=SEMESTRE, programa_id=w.programa.id, fecha_inicio=date(2026, 8, 3),
                                  fecha_fin=date(2026, 12, 12), fecha_c1=date(2026, 9, 18), fecha_c2=date(2026, 10, 23),
                                  fecha_c3=date(2026, 12, 4), activo=True)
        db.add(cal)
    sug = None
    if sugerencia:
        cat = EstrategiaDuaCatalogo(codigo="DUA-T-1.1-01", nombre="Presentar la información en varios formatos",
                                    descripcion_pedagogica="Ofrecer texto, esquema y audio de cada tema.",
                                    principio=PrincipioDua.REPRESENTACION, pauta=1, escenarios=["AULA"],
                                    tipos_barrera=["COMUNICATIVA"])
        db.add(cat)
        db.flush()
        sug = SugerenciaDua(estudiante_id=est.id, barrera_id=barreras[1].id, estrategia_catalogo_id=cat.id,
                            tipo_barrera=TipoBarrera.COMUNICATIVA, principio_dua=PrincipioDua.REPRESENTACION,
                            estado=EstadoSugerencia.ACEPTADA)
        db.add(sug)
    db.commit()
    return {"barreras": barreras, "fortaleza": fort, "calendario": cal, "sugerencia": sug}


class Api:
    """Atajos HTTP con el usuario indicado."""

    def __init__(self, client):
        self.c = client

    def req(self, metodo: str, url: str, user, json=None, **kw):
        return self.c.request(metodo, f"/api/v1{url}", json=json, headers=auth_headers(user), **kw)

    def get(self, url, user, **kw):
        return self.req("GET", url, user, **kw)

    def post(self, url, user, json=None, **kw):
        return self.req("POST", url, user, json or {}, **kw)

    def patch(self, url, user, json=None, **kw):
        return self.req("PATCH", url, user, json or {}, **kw)

    def delete(self, url, user, **kw):
        return self.req("DELETE", url, user, **kw)


def crear_plan(api: Api, w, **body) -> dict:
    r = api.post(f"/estudiantes/{w.estudiante.id}/planes", w.bienestar, body)
    assert r.status_code == 201, r.text
    return r.json()["plan"]


def aceptar_todos(api: Api, w, plan: dict) -> None:
    for a in plan["ajustes"]:
        r = api.post(f"/planes/{plan['id']}/ajustes/{a['id']}/respuesta-estudiante", w.estudiante_user,
                     {"respuesta": "ACEPTADO"})
        assert r.status_code == 200, r.text


def hasta_firmas(api: Api, w, **body) -> dict:
    """Borrador -> concertación -> validación del Coordinador (PENDIENTE_FIRMAS). Devuelve el plan."""
    plan = crear_plan(api, w, **body)
    pid = plan["id"]
    assert api.post(f"/planes/{pid}/enviar-a-estudiante", w.bienestar).status_code == 200
    aceptar_todos(api, w, plan)
    r = api.post(f"/planes/{pid}/enviar-a-validacion", w.bienestar)
    assert r.status_code == 200, r.text
    r = api.post(f"/planes/{pid}/validar", w.coordinador, {"comentario": "Validado"})
    assert r.status_code == 200, r.text
    return plan


def firmar_todos(api: Api, w, pid: int) -> dict:
    ultimo = None
    for u in (w.estudiante_user, w.bienestar, w.coordinador):
        ultimo = api.post(f"/planes/{pid}/firmar", u, {"confirmo": True})
        assert ultimo.status_code == 201, ultimo.text
    return ultimo.json()
