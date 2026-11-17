"""Genera la tabla entidad -> archivo -> campo clave de docs/MODELO.md (ejecutar tras cambiar modelos)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.models  # noqa: E402,F401
from app.core.crypto import EncryptedDate, EncryptedJSON, EncryptedText  # noqa: E402
from app.models import Base  # noqa: E402

ERD = {  # tabla -> seccion ERD
    "usuario": "3.1", "estudiante": "3.2", "caracterizacion": "3.3", "dato_comunicacion": "3.4", "dato_autonomia": "3.5",
    "dato_sensorial": "3.6", "dato_preferencia": "3.7", "perfil_fortalezas": "3.8", "fortaleza": "3.9", "interes": "3.10",
    "estrategia_aprendizaje": "3.11", "contexto_universitario": "3.12", "contexto_aula": "3.13", "contexto_docente": "3.14",
    "contexto_evaluacion": "3.15", "contexto_campus": "3.16", "barrera_identificada": "3.17", "barrera_actitudinal": "3.18",
    "barrera_comunicativa": "3.19", "barrera_pedagogica": "3.20", "barrera_evaluativa": "3.21", "barrera_sensorial": "3.22",
    "barrera_social": "3.23", "barrera_institucional": "3.24", "barrera_tecnologica": "3.25", "facilitador": "3.26",
    "facilitador_personal": "3.27", "facilitador_pedagogico": "3.28", "facilitador_social": "3.29",
    "facilitador_institucional": "3.30", "facilitador_tecnologico": "3.31", "plan_maar_tea": "3.32", "estrategia_dua": "3.33",
    "ajuste_razonable": "3.34", "respuesta_comunicacion": "3.35", "respuesta_pedagogia": "3.36", "respuesta_evaluacion": "3.37",
    "respuesta_ambiente": "3.38", "respuesta_interaccion": "3.39", "respuesta_tecnologia": "3.40", "apoyo": "3.41",
    "tipo_apoyo": "3.42", "responsable_apoyo": "3.43", "recurso": "3.44", "implementacion_apoyo": "3.45",
    "registro_implementacion": "3.46", "seguimiento": "3.47", "registro_seguimiento": "3.48", "evidencia_efectividad": "3.49",
    "resultado_indicador": "3.50", "evaluacion_plan": "3.51", "decision_plan": "3.52", "estado_plan": "3.53",
    "trayectoria_academica": "3.54", "acceso": "3.55", "participacion": "3.56", "aprendizaje": "3.57", "bienestar": "3.58",
    "autonomia": "3.59", "permanencia": "3.60", "progresion": "3.61", "graduacion": "3.62", "transicion_profesional": "3.63",
    "matricula": "3.64", "programa_academico": "3.65", "docente": "3.66", "coordinador_programa": "3.67",
    "personal_administrativo": "3.68", "personal_bienestar": "3.69",
}
V7_ESCENARIOS = {"contexto_virtualidad", "contexto_laboratorio", "contexto_practica_clinica", "contexto_practica_salud_publica",
                 "contexto_evento", "contexto_pasantia"}
EXTRA_SPEC = {"consentimiento", "cuestionario_aq10", "respuesta_aq10", "tarea_negociacion", "log_auditoria",
              "estrategia_dua_catalogo", "sugerencia_dua", "caso_cbr", "calendario_academico", "parametro_sistema",
              "notificacion", "email_outbox", "autorizacion_familiar", "firma_plan", "plan_version",
              "registro_seguimiento_ajuste", "asignatura", "asignacion_docente", "solicitud_ingreso", "nota_continuidad",
              "preferencia_sensorial_ui", "refresh_token", "exportacion"}
EXTRA_OWN = {"hito_trayectoria", "registro_inasistencia"}
AUDIT = {"id", "created_at", "updated_at", "deleted_at", "deleted_reason", "deleted_by_id"}


def origen(t):
    if t in ERD:
        return f"ERD §{ERD[t]}"
    if t in V7_ESCENARIOS:
        return "v7 §7.1 (escenario F3)"
    if t in EXTRA_SPEC:
        return "BUILD_SPEC §4 / v7"
    return "adicional (base)"


rows = []
for name, t in sorted(Base.metadata.tables.items(), key=lambda kv: (kv[1].info.get("o", 0), kv[0])):
    cls = next(m.class_.__name__ for m in Base.registry.mappers if m.local_table is t)
    mod = next(m.class_.__module__ for m in Base.registry.mappers if m.local_table is t).replace("app.models.", "") + ".py"
    fks = [c.name for c in t.columns if c.foreign_keys]
    enc = [c.name for c in t.columns if isinstance(c.type, (EncryptedText, EncryptedJSON, EncryptedDate))]
    biz = [c.name for c in t.columns if c.name not in AUDIT and not c.foreign_keys]
    clave = ", ".join(([f"FK {', '.join(fks[:2])}"] if fks else []) + biz[:2])
    rows.append((name, cls, mod, clave, ", ".join(enc) or "—", origen(name)))

print("| Tabla | Clase | Archivo (`app/models/`) | Campos clave | Cifrados (AES-256-GCM) | Origen |")
print("|---|---|---|---|---|---|")
for r in sorted(rows, key=lambda r: (r[2], r[0])):
    print("| `{}` | `{}` | `{}` | {} | {} | {} |".format(*r))
print()
print("TOTAL", len(rows))
cnt = {"ERD": sum(1 for r in rows if r[5].startswith("ERD")), "v7": sum(1 for r in rows if r[5].startswith("v7 §7.1")),
       "spec": sum(1 for r in rows if r[5].startswith("BUILD")), "extra": sum(1 for r in rows if r[5].startswith("adicional"))}
print(cnt)
