"""Datos semilla del STI (BUILD_SPEC §7).

    python -m scripts.seed                 # solo datos de referencia (seguro en producción)
    SEED_DEMO=1 python -m scripts.seed     # + usuarios demo por rol y 5 estudiantes FICTICIOS

Siempre (idempotente): programa Enfermería (Universidad de Córdoba), calendario 2026-II, parámetros del sistema,
estados del plan (ESTADO_PLAN), AQ-10 de Allison et al. 2012 en español, catálogo DUA CAST 2.2 (3 principios,
9 pautas, 34 estrategias etiquetadas por escenario y tipo de barrera).

Solo con SEED_DEMO=1: usuarios demo (contraseña de demo en `DEMO_PASSWORD`, por defecto la indicada abajo;
CAMBIARLA o no cargar la demo en producción) y 5 estudiantes ficticios en distintas etapas del proceso.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.data import aq10 as aq10_data  # noqa: E402
from app.data.dua_cast import build_catalog  # noqa: E402
from app.models import (  # noqa: E402
    AjusteRazonable,
    AsignacionDocente,
    Asignatura,
    AutorizacionFamiliar,
    BarreraIdentificada,
    CalendarioAcademico,
    Caracterizacion,
    Consentimiento,
    ContextoAula,
    ContextoCampus,
    ContextoUniversitario,
    CuestionarioAQ10,
    DatoComunicacion,
    DatoSensorial,
    Docente,
    EstadoPlan,
    EstrategiaDua,
    EstrategiaDuaCatalogo,
    Estudiante,
    FirmaPlan,
    Fortaleza,
    Interes,
    Matricula,
    PerfilFortalezas,
    PlanMaarTea,
    PlanVersion,
    ProgramaAcademico,
    RespuestaAmbiente,
    RespuestaAQ10,
    Usuario,
)
from app.models.base import utcnow  # noqa: E402
from app.models.enums import (  # noqa: E402
    AlcanceFamiliar,
    DimensionDua,
    EstadoAutorizacionFamiliar,
    EstadoCaracterizacion,
    EstadoConsentimiento,
    EstadoPlanEnum,
    EstadoUsuario,
    ModalidadAQ10,
    NivelAcademico,
    NivelConsolidacion,
    RolFirmante,
    TipoAjuste,
    TipoAmbientalAjuste,
    TipoBarrera,
    TipoSensorial,
    ViaIngreso,
)
from app.services import params  # noqa: E402
from app.services.accounts import create_user  # noqa: E402
from app.services.plan_states import DESCRIPCIONES, TRANSICIONES  # noqa: E402

DEMO_PASSWORD_DEFAULT = "Demo-STI-2026!"
DEMO_DOMAIN = "sti-demo.example.com"
SEMESTRE = "2026-II"

DEMO_USERS = [
    # (clave, rol, nombre, perfil)
    ("bienestar", "BIENESTAR", "Beatriz Bienestar (demo)", {"profesion": "Psicóloga"}),
    ("coordinador", "COORDINADOR", "Carlos Coordinador (demo)", {}),
    ("docente", "DOCENTE", "Diana Docente (demo)", {"especialidad": "Fundamentos de Enfermería"}),
    ("familiar", "FAMILIAR", "Fernanda Familiar (demo)", {}),
]


# ----------------------------------------------------------------------------- referencia
def seed_reference(db: Session) -> dict:
    out: dict = {}
    out["parametros"] = params.ensure_defaults(db)

    # --- estados del plan
    existentes = {e.nombre_estado for e in db.scalars(select(EstadoPlan))}
    n = 0
    for estado, destinos in TRANSICIONES.items():
        if estado.value not in existentes:
            db.add(EstadoPlan(nombre_estado=estado.value, descripcion_estado=DESCRIPCIONES[estado],
                              transiciones_permitidas=[d.value for d in destinos]))
            n += 1
    out["estados_plan"] = n

    # --- programa
    prog = db.scalar(select(ProgramaAcademico).where(ProgramaAcademico.codigo_programa == "ENF"))
    if prog is None:
        prog = ProgramaAcademico(
            nombre_programa="Enfermería", codigo_programa="ENF", nivel_academico=NivelAcademico.PREGRADO,
            duracion_semestres=8, facultad_responsable="Facultad de Ciencias de la Salud — Universidad de Córdoba",
            disponibilidad_ajustes_tea=True, semestre_practicas=7,
            descripcion_programa="Programa piloto del STI (primer semestre, ~30 estudiantes).",
        )
        db.add(prog)
        db.flush()
        out["programa"] = 1

    # --- calendario 2026-II (fechas de ejemplo: el Administrador las ajusta en M1 según el calendario oficial)
    cal = db.scalar(select(CalendarioAcademico).where(CalendarioAcademico.semestre_academico == SEMESTRE,
                                                      CalendarioAcademico.programa_id.is_(None)))
    if cal is None:
        inicio = date(2026, 8, 3)
        db.add(CalendarioAcademico(
            semestre_academico=SEMESTRE, programa_id=None, fecha_inicio=inicio, fecha_fin=inicio + timedelta(weeks=17),
            fecha_c1=inicio + timedelta(weeks=6, days=2), fecha_c2=inicio + timedelta(weeks=11, days=2),
            fecha_c3=inicio + timedelta(weeks=16, days=2), umbral_inasistencia=20, activo=True,
        ))
        out["calendario"] = 1

    # --- AQ-10
    cuest = db.scalar(select(CuestionarioAQ10).where(CuestionarioAQ10.version == "1.0"))
    if cuest is None:
        db.add(CuestionarioAQ10(
            nombre="AQ-10 Adultos (Allison et al., 2012) — español", version="1.0", idioma="es-CO",
            fuente=aq10_data.FUENTE, items=aq10_data.items_json(), opciones=aq10_data.opciones_json(),
            punto_corte=aq10_data.PUNTO_CORTE, revision_linguistica_pendiente=True, activo=True,
        ))
        out["aq10"] = 1

    # --- catálogo DUA
    codigos = set(db.scalars(select(EstrategiaDuaCatalogo.codigo)))
    n = 0
    for item in build_catalog():
        if item["codigo"] not in codigos:
            db.add(EstrategiaDuaCatalogo(**item))
            n += 1
    out["catalogo_dua"] = n
    db.flush()
    return out


# ----------------------------------------------------------------------------- demo
def _get_or_create_user(db: Session, email: str, nombre: str, rol: str, password: str, perfil: dict | None = None,
                        estado: EstadoUsuario | None = None) -> Usuario:
    u = db.scalar(select(Usuario).where(Usuario.email == email))
    if u is None:
        u = create_user(db, email=email, nombre_completo=nombre, rol=rol, password=password, perfil=perfil,
                        estado=estado, skip_password_policy=True)
    return u


def _sign_f0(db: Session, est: Estudiante, user: Usuario) -> None:
    if db.scalar(select(Consentimiento.id).where(Consentimiento.estudiante_id == est.id)):
        return
    firmado = utcnow()
    texto_hash = hashlib.sha256(b"F0-v1").hexdigest()
    firma = hashlib.sha256(f"{est.id}|F0-v1|{texto_hash}|{firmado.isoformat()}".encode()).hexdigest()
    db.add(Consentimiento(
        estudiante_id=est.id, version_texto="F0-v1", texto_hash=texto_hash, acepta_tratamiento_datos_sensibles=True,
        acepta_politica_privacidad=True, firmado_at=firmado, firma_hash=firma, firmado_por_id=user.id,
        estado=EstadoConsentimiento.FIRMADO, ip="127.0.0.1", user_agent="seed",
    ))
    user.estado = EstadoUsuario.ACTIVO


def _apply_aq10(db: Session, est: Estudiante, user: Usuario, bienestar: Usuario, respuestas: dict[int, int]) -> int:
    cuest = db.scalar(select(CuestionarioAQ10).where(CuestionarioAQ10.activo.is_(True)))
    puntaje = 0
    for it in cuest.items:
        r = respuestas[it["numero"]]
        direccion = "ACUERDO" if r in (1, 2) else "DESACUERDO"
        puntaje += 1 if direccion == it["puntua_si"] else 0
    db.add(RespuestaAQ10(
        estudiante_id=est.id, cuestionario_id=cuest.id, aplicado_por_id=bienestar.id, modalidad=ModalidadAQ10.ASISTIDA,
        aplicado_at=utcnow(), respuestas={str(k): v for k, v in respuestas.items()}, puntaje=puntaje,
        punto_corte_aplicado=cuest.punto_corte, supera_umbral=puntaje >= cuest.punto_corte,
        flujo_activado=puntaje >= cuest.punto_corte,
    ))
    return puntaje


def seed_demo(db: Session) -> dict:
    password = os.environ.get("DEMO_PASSWORD", DEMO_PASSWORD_DEFAULT)
    prog = db.scalar(select(ProgramaAcademico).where(ProgramaAcademico.codigo_programa == "ENF"))
    users: dict[str, Usuario] = {}
    for key, rol, nombre, perfil in DEMO_USERS:
        users[key] = _get_or_create_user(db, f"{key}.demo@{DEMO_DOMAIN}", nombre, rol, password, perfil)
    coord = users["coordinador"].coordinador
    coord.programa_responsable_ids = [prog.id]
    docente = db.scalar(select(Docente).where(Docente.usuario_id == users["docente"].id))
    docente.programa_id = prog.id
    prog.coordinador_programa_id = coord.id

    # asignaturas + asignación docente
    asig = db.scalar(select(Asignatura).where(Asignatura.programa_id == prog.id, Asignatura.codigo == "ENF101"))
    if asig is None:
        asig = Asignatura(programa_id=prog.id, codigo="ENF101", nombre="Fundamentos de Enfermería", semestre_plan=1,
                          creditos=4)
        db.add(asig)
        db.add(Asignatura(programa_id=prog.id, codigo="ENF102", nombre="Anatomía y Fisiología", semestre_plan=1,
                          creditos=4))
        db.flush()
    if not db.scalar(select(AsignacionDocente.id).where(AsignacionDocente.docente_id == docente.id)):
        db.add(AsignacionDocente(docente_id=docente.id, asignatura_id=asig.id, semestre_academico=SEMESTRE, grupo="A"))
    db.flush()

    bienestar = users["bienestar"]
    est_defs = [
        # clave, nombre, etapa
        ("est1", "Estudiante Uno (demo)", "invitado"),  # Vía 1: invitación enviada, sin activar
        ("est2", "Estudiante Dos (demo)", "sin_f0"),  # Vía 3: activó, falta firmar F0
        ("est3", "Estudiante Tres (demo)", "f0"),  # F0 firmado, sin AQ-10
        ("est4", "Estudiante Cuatro (demo)", "caracterizacion"),  # AQ-10 >= 6 + F1 + F2
        ("est5", "Estudiante Cinco (demo)", "plan"),  # + F3, F4, plan en IMPLEMENTACION
    ]
    students: dict[str, tuple[Usuario, Estudiante]] = {}
    for i, (key, nombre, etapa) in enumerate(est_defs, start=1):
        email = f"{key}.demo@{DEMO_DOMAIN}"
        # Sin correo (por defecto) nadie puede abrir un enlace de invitación: la cuenta "invitada" ya tiene clave.
        invitado = etapa == "invitado" and get_settings().email_activation_required
        u = db.scalar(select(Usuario).where(Usuario.email == email))
        if u is not None and not u.password_hash and not invitado:  # repara cuentas demo que quedaron sin acceso
            u.password_hash = hash_password(password)
            u.estado = EstadoUsuario.PENDIENTE_CONSENTIMIENTO
            u.activation_token_hash = None
        if u is None:
            u = create_user(
                db, email=email, nombre_completo=nombre, rol="ESTUDIANTE",
                password=None if invitado else password, skip_password_policy=True,
                estado=EstadoUsuario.PENDIENTE_ACTIVACION if invitado else EstadoUsuario.PENDIENTE_CONSENTIMIENTO,
                perfil={"codigo_estudiante": f"DEMO{i:04d}", "programa_id": prog.id, "anio_ingreso": 2026,
                        "semestre_actual": 1,
                        "via_ingreso": ViaIngreso.MATRICULA_CSV if etapa == "sin_f0" else ViaIngreso.BIENESTAR},
            )
        est = db.scalar(select(Estudiante).where(Estudiante.usuario_id == u.id))
        if not db.scalar(select(Matricula.id).where(Matricula.estudiante_id == est.id)):
            db.add(Matricula(estudiante_id=est.id, programa_academico_id=prog.id, semestre_academico=SEMESTRE,
                             fecha_matricula=date(2026, 7, 20), numero_asignaturas=2, creditos_matriculados=8))
        students[key] = (u, est)
        if etapa in ("f0", "caracterizacion", "plan"):
            _sign_f0(db, est, u)
    db.flush()

    # --- est4 y est5: AQ-10 + F1 + F2
    for key in ("est4", "est5"):
        u, est = students[key]
        if db.scalar(select(RespuestaAQ10.id).where(RespuestaAQ10.estudiante_id == est.id)):
            continue
        # patrón con puntaje 7 (ejemplo ficticio)
        _apply_aq10(db, est, u, bienestar, {1: 1, 2: 3, 3: 4, 4: 3, 5: 2, 6: 2, 7: 1, 8: 2, 9: 3, 10: 4})
        car = Caracterizacion(
            estudiante_id=est.id, fecha_caracterizacion=date(2026, 8, 12), profesional_responsable_id=bienestar.id,
            resumen_ejecutivo="Dato ficticio de demostración: estudiante con interés en anatomía; se beneficia de "
                              "instrucciones escritas y ambientes de baja estimulación.",
            autodescripcion_estudiante="(Demo) Me concentro mucho en los detalles y prefiero saber qué va a pasar.",
            estado=EstadoCaracterizacion.COMPLETA, fecha_ultima_actualizacion=utcnow(),
        )
        db.add(car)
        db.flush()
        db.add(DatoSensorial(caracterizacion_id=car.id, tipo_sensorial=TipoSensorial.AUDITIVA, hipersensibilidad=True,
                             descripcion_experiencia="(Demo) Los ruidos de pasillo y los timbres me agotan.",
                             impacto_academico="(Demo) Pierdo la concentración en aulas ruidosas."))
        db.add(DatoComunicacion(caracterizacion_id=car.id, tipo_comunicacion="Comunicación verbal",
                                descripcion="(Demo) Prefiere instrucciones escritas y literales."))
        perfil = PerfilFortalezas(estudiante_id=est.id, fecha_elaboracion=date(2026, 8, 12),
                                  profesional_responsable_id=bienestar.id,
                                  narrativa_fortalezas="(Demo) Memoria detallada y constancia.")
        db.add(perfil)
        db.flush()
        db.add(Fortaleza(perfil_fortalezas_id=perfil.id, nombre_fortaleza="Atención al detalle",
                         descripcion_detallada="(Demo) Detecta errores en procedimientos y registros.",
                         nivel_consolidacion=NivelConsolidacion.CONSOLIDADA))
        db.add(Interes(perfil_fortalezas_id=perfil.id, nombre_interes="Anatomía humana",
                       descripcion="(Demo) Dibuja y memoriza estructuras anatómicas."))
    db.flush()

    # --- est5: F3 + F4 + plan en IMPLEMENTACION con firmas
    u5, e5 = students["est5"]
    if not db.scalar(select(ContextoUniversitario.id).where(ContextoUniversitario.estudiante_id == e5.id)):
        ctx = ContextoUniversitario(estudiante_id=e5.id, programa_academico_id=prog.id, semestre_academico=SEMESTRE,
                                    fecha_analisis=date(2026, 8, 14), responsable_analisis_id=bienestar.id,
                                    resumen_contextual="(Demo) Aulas de 35 estudiantes con ruido de pasillo.")
        db.add(ctx)
        db.flush()
        db.add(ContextoAula(contexto_universitario_id=ctx.id, numero_estudiantes=35, caracteristicas_ambientales="Ruido de pasillo"))
        db.add(ContextoCampus(contexto_universitario_id=ctx.id, disponibilidad_espacios_tranquilos=False))
    if not db.scalar(select(PlanMaarTea.id).where(PlanMaarTea.estudiante_id == e5.id)):
        barrera = BarreraIdentificada(
            estudiante_id=e5.id, tipo_barrera=TipoBarrera.SENSORIAL, descripcion_barrera="(Demo) Ruido constante en el aula.",
            fecha_identificacion=date(2026, 8, 14), semestre_academico=SEMESTRE, registrada_por_id=bienestar.id,
            impacto_aprendizaje=True,
        )
        db.add(barrera)
        db.flush()
        plan = PlanMaarTea(
            estudiante_id=e5.id, fecha_elaboracion=date(2026, 8, 20), semestre_academico=SEMESTRE,
            vigencia_inicio=date(2026, 8, 24), vigencia_fin=date(2026, 12, 12), estado=EstadoPlanEnum.IMPLEMENTACION,
            resumen_ejecutivo="(Demo) Plan MAAR-TEA de ejemplo.", elaborado_por_id=bienestar.id,
            profesionales_responsables_ids=[bienestar.id], fecha_aprobacion=date(2026, 8, 28),
            aprobado_por_id=users["coordinador"].id, validado_por_id=users["coordinador"].id,
        )
        db.add(plan)
        db.flush()
        ajuste = AjusteRazonable(
            plan_id=plan.id, barrera_asociada_id=barrera.id, nombre_ajuste="Ubicación en zona de menor ruido",
            descripcion_ajuste="(Demo) Puede sentarse en las filas de adelante, lejos de la puerta.",
            justificacion="Reduce la sobrecarga auditiva.", tipo_ajuste=TipoAjuste.AMBIENTE,
            fecha_inicio=date(2026, 8, 24), asignatura_id=asig.id, responsable_id=users["docente"].id,
            estado="ACTIVO", aceptado_por_estudiante=True, aceptado_por_estudiante_at=utcnow(),
        )
        db.add(ajuste)
        db.flush()
        db.add(RespuestaAmbiente(ajuste_id=ajuste.id, tipo_ambiental_ajuste=TipoAmbientalAjuste.UBICACION_ESPECIFICA,
                                 descripcion="Filas centrales-frontales."))
        cat = db.scalar(select(EstrategiaDuaCatalogo).where(EstrategiaDuaCatalogo.punto_verificacion == "7.3").order_by(EstrategiaDuaCatalogo.id))
        db.add(EstrategiaDua(
            plan_id=plan.id, nombre_estrategia=cat.nombre, descripcion=cat.descripcion_pedagogica,
            dimension_dua=DimensionDua.MULTIPLES_MEDIOS_PARTICIPACION, responsable_implementacion_id=users["docente"].id,
            alcance="Todo el grupo", estrategia_catalogo_id=cat.id, asignatura_id=asig.id,
            escenario="AULA",
        ))
        snapshot = {"plan_id": plan.id, "version": 1, "ajustes": [ajuste.nombre_ajuste], "estrategias_dua": [cat.codigo]}
        canon = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(canon.encode()).hexdigest()
        db.add(PlanVersion(plan_id=plan.id, version=1, estado_plan=plan.estado.value, snapshot=snapshot, hash_snapshot=h,
                           motivo_cambio="Versión inicial (demo)", creado_por_id=bienestar.id))
        for rol, firmante in ((RolFirmante.ESTUDIANTE, u5), (RolFirmante.BIENESTAR, bienestar),
                              (RolFirmante.COORDINADOR, users["coordinador"])):
            ahora = utcnow()
            db.add(FirmaPlan(plan_id=plan.id, version=1, rol_firmante=rol, firmante_id=firmante.id, firmado_at=ahora,
                             hash_documento=h,
                             firma_hash=hashlib.sha256(f"{h}|{firmante.id}|{ahora.isoformat()}".encode()).hexdigest()))
        # autorización familiar de ejemplo (solo plan y seguimiento)
        db.add(AutorizacionFamiliar(
            estudiante_id=e5.id, familiar_usuario_id=users["familiar"].id, familiar_nombre=users["familiar"].nombre_completo,
            familiar_email=users["familiar"].email, parentesco="Madre (demo)",
            alcance=[AlcanceFamiliar.PLAN.value, AlcanceFamiliar.SEGUIMIENTO.value],
            estado=EstadoAutorizacionFamiliar.VIGENTE, otorgada_at=utcnow(),
        ))
    db.flush()
    return {"usuarios": [u.email for u in users.values()] + [u.email for u, _ in students.values()]}


def run_seed(db: Session, demo: bool | None = None) -> dict:
    demo = get_settings().seed_demo if demo is None else demo
    out = {"referencia": seed_reference(db)}
    # Slice A (calendario, parámetros, AQ-10 versionado) también aplica sin demo.
    from scripts import seed_extra_a

    out["extra_a"] = seed_extra_a.seed(db, demo)
    if demo:
        out["demo"] = seed_demo(db)
        # Orden: B (F1–F5, CBR) → C1 (planes, firmas, matriz) → C2 (seguimiento, F9) → C3 (trayectoria, familiar).
        from scripts import seed_extra_b, seed_extra_c1, seed_extra_c2, seed_extra_c3

        for nombre, modulo in (("extra_b", seed_extra_b), ("extra_c1", seed_extra_c1),
                               ("extra_c2", seed_extra_c2), ("extra_c3", seed_extra_c3)):
            out[nombre] = modulo.seed(db)
    return out


def main() -> None:
    demo = os.environ.get("SEED_DEMO", "").lower() in ("1", "true", "yes", "si", "sí") or get_settings().seed_demo
    with session_scope() as db:
        result = run_seed(db, demo)
    print("Semilla aplicada:", json.dumps(result["referencia"], ensure_ascii=False))
    if demo:
        pwd = os.environ.get("DEMO_PASSWORD", DEMO_PASSWORD_DEFAULT)
        print("\nUSUARIOS DEMO (cambie la contraseña o no cargue la demo en producción)")
        print(f"  contraseña: {pwd}")
        for e in result["demo"]["usuarios"]:
            print("  -", e)
    else:
        print("(Sin SEED_DEMO=1: no se crearon usuarios demo. Cree el admin con scripts/create_admin.py)")


if __name__ == "__main__":
    main()
