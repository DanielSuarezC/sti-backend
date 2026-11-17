"""Ayudas para las pruebas del slice B (estado vía API + modelos)."""

from __future__ import annotations

from app.data import f0_texto
from tests.factories import auth_headers, make_estudiante

A_NOMBRE_OK = "Estudiante Prueba"


def f0_body(nombre: str, **kw) -> dict:
    body = {
        "version_texto": f0_texto.VERSION, "texto_hash": f0_texto.texto_hash(), "nombre_firmante": nombre,
        "acepta_tratamiento_general": True, "acepta_datos_sensibles_salud": True, "acepta_compartir_ajustes_docentes": True,
    }
    body.update(kw)
    return body


def student_without_consent(db, programa):
    u, est = make_estudiante(db, programa, consent=False, nombre=A_NOMBRE_OK)
    return u, est


def h(user) -> dict:
    return auth_headers(user)


F1_SECCIONES = {
    "historia_academica": {"trayectoria_escolar": "Colegio público; buen rendimiento en ciencias.", "apoyos_previos": "Ninguno formal."},
    "comunicacion": {"items": [{"tipo_comunicacion": "Verbal", "descripcion": "Prefiere instrucciones escritas y literales."}]},
    "sensorial": {"items": [{"tipo_sensorial": "AUDITIVA", "hipersensibilidad": True, "descripcion_experiencia": "Los timbres lo agotan."}]},
    "autonomia": {"items": [{"contexto_autonomia": "Estudio en casa", "nivel_autonomia": "ALTA"}]},
    "preferencias": {"items": [{"tipo_preferencia": "Material anticipado", "descripcion": "Recibir las guías antes de clase."}]},
    "resumen": {"resumen_ejecutivo": "Estudiante con interés en anatomía; se beneficia de estructura y anticipación."},
}


def fill_and_confirm_f1(client, bienestar, est_id: int) -> None:
    for sec, body in F1_SECCIONES.items():
        r = client.patch(f"/api/v1/estudiantes/{est_id}/caracterizacion/{sec}", json=body, headers=h(bienestar))
        assert r.status_code == 200, (sec, r.text)
    r = client.post(f"/api/v1/estudiantes/{est_id}/caracterizacion/confirmar", headers=h(bienestar))
    assert r.status_code == 200, r.text


_ACUERDO = {1, 7, 8, 10}  # ítems que puntúan con "de acuerdo" (Allison 2012)


def aq10_answers(puntaje: int) -> dict[str, int]:
    """Respuestas que producen exactamente `puntaje` (0-10): los primeros `puntaje` ítems puntúan, el resto no."""
    out = {}
    for n in range(1, 11):
        puntua = n <= puntaje
        acuerdo = n in _ACUERDO
        out[str(n)] = (1 if acuerdo else 4) if puntua else (4 if acuerdo else 1)
    return out
