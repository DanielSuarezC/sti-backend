"""Motor DUA M3: sugerencias, decisiones y texto accesible. Ver docs/api/slice_b.md.

# OWNER: slice B
Sugiere, nunca impone. Bienestar decide; Coordinador lee; el estudiante ve solo lo acordado.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.core.errors import Forbidden
from app.models.dua import EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import Escenario, EstadoSugerencia, PrincipioDua, Rol, TipoBarrera
from app.models.usuarios import Usuario
from app.schemas.sugerencias import AceptarIn, GenerarIn, ModificarIn, RechazarIn
from app.services import sugerencias as svc
from app.services.b_common import AccionB

router = APIRouter(tags=["sugerencias"])

_LEER = require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.ESTUDIANTE)
_BIENESTAR = require_roles_consent(Rol.BIENESTAR)


@router.post("/estudiantes/{estudiante_id}/sugerencias/generar", status_code=201, summary="Generar sugerencias DUA (CBR + reglas)")
def generar(estudiante_id: int, body: GenerarIn, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_BIENESTAR)):
    est = assert_can(db, user, estudiante_id, Recurso.BARRERAS, Accion.ESCRIBIR)
    r = svc.generate(db, est, barrera_ids=body.barrera_ids, max_por_barrera=body.max_por_barrera)
    audit.log(db, user, AccionB.SUGERENCIAS_GENERADAS, "sugerencia_dua", None,
              {"creadas": len(r["creadas"]), "actualizadas": len(r["actualizadas"]), "sin_cobertura": r["barreras_sin_cobertura"]},
              request=request, estudiante_id=est.id)
    db.commit()
    return {
        "creadas": [svc.serialize(db, s) for s in r["creadas"]], "actualizadas": [svc.serialize(db, s) for s in r["actualizadas"]],
        "barreras_evaluadas": r["barreras_evaluadas"], "barreras_sin_cobertura": r["barreras_sin_cobertura"],
        "detail": "Estas son sugerencias: usted decide si acepta, modifica o rechaza cada una.",
    }


@router.get("/estudiantes/{estudiante_id}/sugerencias", summary="Sugerencias DUA de un estudiante")
def listar(estudiante_id: int, estado: EstadoSugerencia | None = None, principio: PrincipioDua | None = None,
           pauta: int | None = None, escenario: Escenario | None = None, tipo_barrera: TipoBarrera | None = None,
           barrera_id: int | None = None, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    assert_can(db, user, estudiante_id, Recurso.BARRERAS, Accion.LEER)
    solo = str(user.rol) == Rol.ESTUDIANTE  # el estudiante ve solo lo acordado (aceptado o modificado)
    rows = svc.list_for_student(db, estudiante_id, estado=estado, principio=principio, pauta=pauta, escenario=escenario,
                                tipo_barrera=tipo_barrera, barrera_id=barrera_id, solo_vigentes=solo)
    return {"items": [svc.serialize(db, s) for s in rows], "total": len(rows)}


@router.get("/sugerencias/catalogo", summary="Catálogo DUA filtrado (solo lectura)")
def catalogo(principio: PrincipioDua | None = None, pauta: int | None = None, escenario: Escenario | None = None,
             tipo_barrera: TipoBarrera | None = None, db: Session = Depends(get_db),
             user: Usuario = Depends(require_roles_consent(Rol.BIENESTAR, Rol.COORDINADOR, Rol.DOCENTE))):
    stmt = select(EstrategiaDuaCatalogo).where(EstrategiaDuaCatalogo.activo.is_(True))
    if principio:
        stmt = stmt.where(EstrategiaDuaCatalogo.principio == principio)
    if pauta is not None:
        stmt = stmt.where(EstrategiaDuaCatalogo.pauta == pauta)
    rows = [c for c in db.scalars(stmt.order_by(EstrategiaDuaCatalogo.codigo))
            if (escenario is None or str(escenario) in [str(x) for x in (c.escenarios or [])])
            and (tipo_barrera is None or str(tipo_barrera) in [str(x) for x in (c.tipos_barrera or [])])]
    return {"items": [{"id": c.id, "codigo": c.codigo, "nombre": c.nombre, "descripcion_pedagogica": c.descripcion_pedagogica,
                       "principio": str(c.principio), "pauta": c.pauta, "pauta_nombre": c.pauta_nombre,
                       "punto_verificacion": c.punto_verificacion, "escenarios": c.escenarios, "tipos_barrera": c.tipos_barrera}
                      for c in rows], "total": len(rows)}


def _access(db: Session, user: Usuario, sugerencia_id: int, accion: Accion) -> SugerenciaDua:
    s = svc.get_suggestion(db, sugerencia_id)
    assert_can(db, user, s.estudiante_id, Recurso.BARRERAS, accion)
    if str(user.rol) == Rol.ESTUDIANTE and s.estado not in (EstadoSugerencia.ACEPTADA, EstadoSugerencia.MODIFICADA):
        raise Forbidden("Usted solo puede ver las estrategias que ya fueron acordadas.", "ACCESO_DENEGADO")
    return s


@router.get("/sugerencias/{sugerencia_id}", summary="Detalle de una sugerencia")
def ver(sugerencia_id: int, db: Session = Depends(get_db), user: Usuario = Depends(_LEER)):
    return svc.serialize(db, _access(db, user, sugerencia_id, Accion.LEER))


@router.post("/sugerencias/{sugerencia_id}/aceptar", summary="Aceptar la sugerencia")
def aceptar(sugerencia_id: int, request: Request, body: AceptarIn | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(_BIENESTAR)):
    s = _access(db, user, sugerencia_id, Accion.ESCRIBIR)
    svc.accept(db, s, user, body.nota if body else None)
    audit.log(db, user, AccionB.SUGERENCIA_ACEPTADA, "sugerencia_dua", s.id, None, request=request, estudiante_id=s.estudiante_id)
    db.commit()
    return svc.serialize(db, s)


@router.post("/sugerencias/{sugerencia_id}/modificar", summary="Guardar una versión modificada")
def modificar(sugerencia_id: int, body: ModificarIn, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_BIENESTAR)):
    s = _access(db, user, sugerencia_id, Accion.ESCRIBIR)
    svc.modify(db, s, user, body.texto_modificado, body.motivo)
    audit.log(db, user, AccionB.SUGERENCIA_MODIFICADA, "sugerencia_dua", s.id, None, request=request, estudiante_id=s.estudiante_id)
    db.commit()
    return svc.serialize(db, s)


@router.post("/sugerencias/{sugerencia_id}/rechazar", summary="Rechazar con motivo (retroalimenta el CBR)")
def rechazar(sugerencia_id: int, body: RechazarIn, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_BIENESTAR)):
    s = _access(db, user, sugerencia_id, Accion.ESCRIBIR)
    svc.reject(db, s, user, body.motivo)
    audit.log(db, user, AccionB.SUGERENCIA_RECHAZADA, "sugerencia_dua", s.id, {"motivo_registrado": True}, request=request,
              estudiante_id=s.estudiante_id)
    db.commit()
    return svc.serialize(db, s)


@router.post("/sugerencias/{sugerencia_id}/texto-accesible", summary="Generar texto accesible para docentes (IA o plantilla)")
def texto_accesible(sugerencia_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(_BIENESTAR)):
    s = _access(db, user, sugerencia_id, Accion.ESCRIBIR)
    res = svc.accessible_text(db, s)
    audit.log(db, user, AccionB.TEXTO_ACCESIBLE, "sugerencia_dua", s.id, {"origen": res.origen}, request=request,
              estudiante_id=s.estudiante_id)
    db.commit()
    return {"sugerencia_id": s.id, "texto_accesible": res.texto, "origen": res.origen, "modelo": res.modelo}
