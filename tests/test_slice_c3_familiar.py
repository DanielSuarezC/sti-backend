"""Familiar Autorizado (D9, HU-22/28, Ley 1996/2019): otorgar/revocar, alcance granular, solo lectura."""

from __future__ import annotations

import pytest

from datetime import date, timedelta

from sqlalchemy import select

from app.models import EmailOutbox, Notificacion, Seguimiento, Usuario
from app.models.enums import Corte, EstadoUsuario, Rol, Semaforo
from app.services import familiar as svc_fam
from tests.c3_helpers import CENTINELAS, plan_con_datos_clinicos
from tests.factories import auth_headers, authorize_familiar, make_estudiante, make_user

API = "/api/v1"
ALC_TODO = {"plan": True, "seguimiento": True, "caracterizacion": True, "notificaciones": True}


def _otorgar(client, user, **kw):
    body = {"nombre": "Marta Pérez", "email": "marta.familiar@example.com", "parentesco": "Madre",
            "alcance": {"plan": True}, **kw}
    return client.post(f"{API}/estudiantes/mi/familiares", headers=auth_headers(user), json=body)


@pytest.mark.usefixtures("con_correo")
def test_estudiante_otorga_invita_y_lista(client, db, world):
    r = _otorgar(client, world.estudiante_user, alcance=ALC_TODO, vigencia_hasta=(date.today() + timedelta(days=30)).isoformat())
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["estado"] == "PENDIENTE" and a["cuenta_activada"] is False and a["alcance"] == ALC_TODO
    assert a["vigencia_hasta"] is not None
    fam = db.scalar(select(Usuario).where(Usuario.email == "marta.familiar@example.com"))
    assert fam.rol == Rol.FAMILIAR and fam.estado == EstadoUsuario.PENDIENTE_ACTIVACION and fam.activation_token_hash
    asuntos = [m.asunto for m in db.scalars(select(EmailOutbox).where(EmailOutbox.usuario_id == fam.id))]
    assert len(asuntos) == 2 and any("autorizó" in s for s in asuntos)  # invitación + aviso de quién autorizó
    lista = client.get(f"{API}/estudiantes/mi/familiares", headers=auth_headers(world.estudiante_user)).json()
    assert [x["id"] for x in lista] == [a["id"]]
    db.refresh(world.estudiante)
    assert world.estudiante.familia_autoriza_participacion is True


def test_otorgar_validaciones(client, db, world):
    h = auth_headers(world.estudiante_user)
    r = _otorgar(client, world.estudiante_user, alcance={})
    assert r.status_code == 422 and r.json()["code"] == "ALCANCE_VACIO"
    r = _otorgar(client, world.estudiante_user, email=world.estudiante_user.email)
    assert r.status_code == 422 and r.json()["code"] == "CORREO_PROPIO"
    r = _otorgar(client, world.estudiante_user, email=world.bienestar.email)
    assert r.status_code == 409 and r.json()["code"] == "CORREO_EN_USO"
    r = _otorgar(client, world.estudiante_user, vigencia_hasta=(date.today() - timedelta(days=1)).isoformat())
    assert r.status_code == 422 and r.json()["code"] == "VIGENCIA_INVALIDA"
    assert _otorgar(client, world.estudiante_user).status_code == 201
    assert _otorgar(client, world.estudiante_user).json()["code"] == "AUTORIZACION_DUPLICADA"
    assert client.post(f"{API}/estudiantes/mi/familiares", headers=h, json={"nombre": "X"}).status_code == 422


def test_solo_el_estudiante_gestiona_autorizaciones(client, db, world):
    for u in (world.bienestar, world.coordinador, world.docente, world.familiar, world.admin):
        r = _otorgar(client, u)
        assert r.status_code == 403, (u.rol, r.text)
        assert client.get(f"{API}/estudiantes/mi/familiares", headers=auth_headers(u)).status_code == 403
    sin_f0, _ = make_estudiante(db, world.programa, consent=False)
    r = _otorgar(client, sin_f0)
    assert r.status_code == 403 and r.json()["code"] == "CONSENTIMIENTO_REQUERIDO"


def test_alcance_parcial_plan_si_seguimiento_y_caracterizacion_no(client, db, world):
    plan_con_datos_clinicos(db, world)
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    h = auth_headers(world.familiar)
    est = world.estudiante.id
    r = client.get(f"{API}/familiar/estudiantes/{est}/plan", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["ajustes"][0]["nombre_ajuste"]
    for ruta in ("seguimiento", "caracterizacion"):
        r = client.get(f"{API}/familiar/estudiantes/{est}/{ruta}", headers=h)
        assert r.status_code == 403 and r.json()["code"] == "ACCESO_DENEGADO"
    lst = client.get(f"{API}/familiar/estudiantes", headers=h).json()
    assert lst[0]["estudiante_id"] == est and lst[0]["alcance"]["plan"] and not lst[0]["alcance"]["seguimiento"]


def test_familiar_nunca_ve_aq10_notas_ni_barreras(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN", "SEGUIMIENTO", "CARACTERIZACION"])
    h = auth_headers(world.familiar)
    est = world.estudiante.id
    plan_json = client.get(f"{API}/familiar/estudiantes/{est}/plan", headers=h).json()
    seg_json = client.get(f"{API}/familiar/estudiantes/{est}/seguimiento", headers=h).json()
    car_json = client.get(f"{API}/familiar/estudiantes/{est}/caracterizacion", headers=h)
    assert car_json.status_code == 200
    car_json = car_json.json()
    # F1 sí es visible (alcance autorizado), pero nunca AQ-10, diagnóstico, notas de continuidad ni barreras ni justificación
    assert car_json["caracterizacion"]["resumen_ejecutivo"] == "CENTINELA_F1_RESUMEN"
    for payload in (plan_json, seg_json, car_json):
        texto = str(payload)
        for c in ("CENTINELA_DIAGNOSTICO", "CENTINELA_NOTA_CONTINUIDAD", "Ruido en el aula", "Reduce ruido y sobrecarga"):
            assert c not in texto
        assert "puntaje" not in texto and "aq10" not in texto.lower()
    assert "justificacion" not in str(plan_json)
    assert CENTINELAS  # lista usada en otras pruebas


def test_seguimiento_visible_con_alcance(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    from app.models import RegistroSeguimientoAjuste

    seg = Seguimiento(estudiante_id=world.estudiante.id, plan_id=plan.id, corte=Corte.C1, fecha_seguimiento=date.today(),
                      profesional_responsable_id=world.bienestar.id, semaforo_estado=Semaforo.VERDE,
                      descripcion_situacion_actual="CENTINELA_F1_RESUMEN")
    db.add(seg)
    db.flush()
    db.add(RegistroSeguimientoAjuste(seguimiento_id=seg.id, ajuste_id=ajuste.id, corte=Corte.C1, semaforo=Semaforo.VERDE,
                                     implementado=True, comentario_estudiante="CENTINELA_COMENTARIO_ESTUDIANTE",
                                     registrado_por_id=world.bienestar.id))
    db.commit()
    authorize_familiar(db, world.estudiante, world.familiar, ["SEGUIMIENTO"])
    r = client.get(f"{API}/familiar/estudiantes/{world.estudiante.id}/seguimiento", headers=auth_headers(world.familiar))
    assert r.status_code == 200
    c = r.json()["cortes"][0]
    assert c["corte"] == "C1" and c["ajustes"][0]["semaforo"] == "VERDE"
    assert "CENTINELA" not in str(r.json())  # sin narrativas ni percepción del estudiante


def test_sin_autorizacion_403_aunque_el_estudiante_no_exista(client, db, world):
    plan_con_datos_clinicos(db, world)
    h = auth_headers(world.familiar)
    for est_id in (world.estudiante.id, world.otro_estudiante.id, 99999):
        for ruta in ("plan", "seguimiento", "caracterizacion"):
            r = client.get(f"{API}/familiar/estudiantes/{est_id}/{ruta}", headers=h)
            assert r.status_code == 403 and r.json()["code"] == "ACCESO_DENEGADO"
    assert client.get(f"{API}/familiar/estudiantes", headers=h).json() == []
    # autorizado para un estudiante, no para el otro
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    assert client.get(f"{API}/familiar/estudiantes/{world.otro_estudiante.id}/plan", headers=h).status_code == 403
    # otros roles no usan /familiar
    assert client.get(f"{API}/familiar/estudiantes", headers=auth_headers(world.bienestar)).status_code == 403


def test_mutaciones_prohibidas_para_el_familiar(client, db, world):
    plan, ajuste = plan_con_datos_clinicos(db, world)
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN", "SEGUIMIENTO", "CARACTERIZACION"])
    h = auth_headers(world.familiar)
    est = world.estudiante.id
    for metodo in ("post", "put", "patch", "delete"):
        for ruta in (f"/familiar/estudiantes/{est}/plan", "/familiar/estudiantes", f"/familiar/estudiantes/{est}/seguimiento"):
            r = client.request(metodo.upper(), f"{API}{ruta}", headers=h, json={})
            assert r.status_code == 403 and r.json()["code"] == "FAMILIAR_SOLO_LECTURA", (metodo, ruta, r.text)
    # tampoco puede usar las rutas de escritura de otros módulos de este slice
    for metodo, ruta, body in (
        ("post", "/estudiantes/mi/familiares", {"nombre": "X Y", "email": "x@example.com", "alcance": {"plan": True}}),
        ("post", f"/docente/ajustes/{ajuste.id}/implementacion", {"implementado": True, "fecha": date.today().isoformat()}),
        ("post", f"/estudiantes/{est}/f10/borrador", {}),
        ("patch", f"/estudiantes/{est}/trayectoria/2026-II", {}),
    ):
        r = client.request(metodo.upper(), f"{API}{ruta}", headers=h, json=body)
        assert r.status_code == 403, (ruta, r.text)
    r = client.post(f"{API}/familiar/estudiantes/{est}/plan", json={})
    assert r.status_code == 401


def test_revocar_corta_el_acceso_al_instante(client, db, world):
    plan_con_datos_clinicos(db, world)
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN", "SEGUIMIENTO"])
    hf, he = auth_headers(world.familiar), auth_headers(world.estudiante_user)
    est = world.estudiante.id
    assert client.get(f"{API}/familiar/estudiantes/{est}/plan", headers=hf).status_code == 200  # mismo token antes y después
    r = client.delete(f"{API}/estudiantes/mi/familiares/{a.id}?motivo=Ya%20no%20lo%20necesito", headers=he)
    assert r.status_code == 200 and r.json()["estado"] == "REVOCADA" and r.json()["motivo_revocacion"]
    r = client.get(f"{API}/familiar/estudiantes/{est}/plan", headers=hf)
    assert r.status_code == 403  # cuenta inactiva (sin otras autorizaciones) ...
    assert r.json()["code"] == "CUENTA_INACTIVA"
    db.expire_all()
    assert db.get(Usuario, world.familiar.id).estado == EstadoUsuario.INACTIVO
    # la fila se conserva (trazabilidad) y no aparece entre las activas
    assert client.get(f"{API}/estudiantes/mi/familiares", headers=he).json() == []
    assert len(client.get(f"{API}/estudiantes/mi/familiares?incluir_revocadas=true", headers=he).json()) == 1
    assert client.delete(f"{API}/estudiantes/mi/familiares/{a.id}", headers=he).status_code == 409
    from app.models import LogAuditoria

    acciones = [x.accion for x in db.scalars(select(LogAuditoria))]
    assert "AUTORIZACION_FAMILIAR_REVOCADA" in acciones


def test_revocar_una_no_afecta_otra_y_no_desactiva_la_cuenta(client, db, world):
    plan_con_datos_clinicos(db, world)
    a1 = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    authorize_familiar(db, world.otro_estudiante, world.familiar, ["PLAN"])
    hf = auth_headers(world.familiar)
    r = client.delete(f"{API}/estudiantes/mi/familiares/{a1.id}", headers=auth_headers(world.estudiante_user))
    assert r.status_code == 200
    assert client.get(f"{API}/familiar/estudiantes/{world.estudiante.id}/plan", headers=hf).status_code == 403
    lst = client.get(f"{API}/familiar/estudiantes", headers=hf)
    assert lst.status_code == 200 and [x["estudiante_id"] for x in lst.json()] == [world.otro_estudiante.id]


def test_un_estudiante_no_puede_revocar_la_autorizacion_de_otro(client, db, world):
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    r = client.delete(f"{API}/estudiantes/mi/familiares/{a.id}", headers=auth_headers(world.otro_estudiante_user))
    assert r.status_code == 404
    r = client.patch(f"{API}/estudiantes/mi/familiares/{a.id}", headers=auth_headers(world.otro_estudiante_user),
                     json={"alcance": {"plan": False}})
    assert r.status_code == 404


def test_patch_alcance_cambia_acceso_de_inmediato(client, db, world):
    plan_con_datos_clinicos(db, world)
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN", "SEGUIMIENTO"])
    he, hf = auth_headers(world.estudiante_user), auth_headers(world.familiar)
    est = world.estudiante.id
    assert client.get(f"{API}/familiar/estudiantes/{est}/seguimiento", headers=hf).status_code == 200
    r = client.patch(f"{API}/estudiantes/mi/familiares/{a.id}", headers=he, json={"alcance": {"seguimiento": False}})
    assert r.status_code == 200 and r.json()["alcance"] == {"plan": True, "seguimiento": False, "caracterizacion": False,
                                                            "notificaciones": False}
    assert client.get(f"{API}/familiar/estudiantes/{est}/seguimiento", headers=hf).status_code == 403
    assert client.get(f"{API}/familiar/estudiantes/{est}/plan", headers=hf).status_code == 200
    r = client.patch(f"{API}/estudiantes/mi/familiares/{a.id}", headers=he, json={"alcance": {"plan": False}})
    assert r.status_code == 422 and r.json()["code"] == "ALCANCE_VACIO"
    r = client.patch(f"{API}/estudiantes/mi/familiares/{a.id}", headers=he,
                     json={"vigencia_hasta": (date.today() + timedelta(days=5)).isoformat(), "parentesco": "Tía"})
    assert r.status_code == 200 and r.json()["vigencia_hasta"] and r.json()["parentesco"] == "Tía"


def test_vigencia_vencida_corta_el_acceso(client, db, world):
    plan_con_datos_clinicos(db, world)
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    from app.models.base import utcnow

    a.expira_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"{API}/familiar/estudiantes/{world.estudiante.id}/plan",
                      headers=auth_headers(world.familiar)).status_code == 403
    lista = client.get(f"{API}/estudiantes/mi/familiares?incluir_revocadas=true",
                       headers=auth_headers(world.estudiante_user)).json()
    assert lista[0]["estado"] == "EXPIRADA"


def test_reautorizar_tras_revocar_reactiva_la_cuenta(client, db, world):
    a = authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    he = auth_headers(world.estudiante_user)
    client.delete(f"{API}/estudiantes/mi/familiares/{a.id}", headers=he)
    r = client.post(f"{API}/estudiantes/mi/familiares", headers=he,
                    json={"nombre": "Fam", "email": world.familiar.email, "alcance": {"plan": True}})
    assert r.status_code == 201 and r.json()["estado"] == "VIGENTE" and r.json()["cuenta_activada"] is True
    db.expire_all()
    assert db.get(Usuario, world.familiar.id).estado == EstadoUsuario.ACTIVO


def test_notificaciones_de_seguimiento_solo_si_el_estudiante_lo_autorizo(db, world):
    otro_fam = make_user(db, Rol.FAMILIAR)
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN", "NOTIFICACIONES"])
    authorize_familiar(db, world.estudiante, otro_fam, ["PLAN"])
    n = svc_fam.notificar_seguimiento(db, world.estudiante.id, "C1", "2026-II")
    db.commit()
    assert n == 1
    assert db.scalars(select(Notificacion).where(Notificacion.usuario_id == world.familiar.id)).all()
    assert not db.scalars(select(Notificacion).where(Notificacion.usuario_id == otro_fam.id)).all()
    assert svc_fam.notificar_seguimiento(db, world.estudiante.id, "C1", "2026-II") == 1  # idempotente por dedupe_key
    db.commit()
    assert len(db.scalars(select(Notificacion).where(Notificacion.usuario_id == world.familiar.id)).all()) == 1


def test_estudiante_sin_consentimiento_vigente_bloquea_al_familiar(client, db, world):
    plan_con_datos_clinicos(db, world)
    authorize_familiar(db, world.estudiante, world.familiar, ["PLAN"])
    from app.models import Consentimiento
    from app.models.enums import EstadoConsentimiento

    for c in db.scalars(select(Consentimiento)):
        c.estado = EstadoConsentimiento.REVOCADO
    db.commit()
    r = client.get(f"{API}/familiar/estudiantes/{world.estudiante.id}/plan", headers=auth_headers(world.familiar))
    assert r.status_code == 403
