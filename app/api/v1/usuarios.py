"""Usuarios, programas académicos y asignaturas (M1, RF-03/04, HU-03) + Vía 1 (alta de estudiante por Bienestar).

# OWNER: slice A. Contrato en `docs/api/slice_a.md`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import get_db, require_roles
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.security import revoke_all_user_tokens
from app.models.academico import AsignacionDocente, Asignatura, ProgramaAcademico
from app.models.base import utcnow
from app.models.enums import EstadoUsuario, Rol, ViaIngreso
from app.models.usuarios import (
    CoordinadorPrograma,
    Docente,
    Estudiante,
    PersonalAdministrativo,
    PersonalBienestar,
    Usuario,
)
from app.schemas.usuarios import (
    AsignacionCreate,
    AsignaturaCreate,
    AsignaturaUpdate,
    EstudianteVia1,
    MotivoBody,
    ProgramaCreate,
    ProgramaUpdate,
    UsuarioCreate,
    UsuarioUpdate,
)
from app.services import student_intake
from app.services.accounts import create_user, invite_user, normalize_email

# OWNER: slice A
router = APIRouter(prefix="/usuarios", tags=["usuarios"])

ADMIN = Depends(require_roles(Rol.ADMIN))
ADMIN_BIENESTAR = Depends(require_roles(Rol.ADMIN, Rol.BIENESTAR))
LECTORES_PROG = Depends(require_roles(Rol.ADMIN, Rol.BIENESTAR, Rol.COORDINADOR))


# ----------------------------------------------------------------------------- helpers
def _perfil_dict(db: Session, u: Usuario) -> dict:
    rol = str(u.rol)
    out: dict = {"programa_id": None, "programas_ids": []}
    if rol == Rol.ESTUDIANTE:
        e = db.scalar(select(Estudiante).where(Estudiante.usuario_id == u.id))
        if e:
            out.update(programa_id=e.programa_id, codigo_estudiante=e.codigo_estudiante, via_ingreso=str(e.via_ingreso))
    elif rol == Rol.DOCENTE:
        d = db.scalar(select(Docente).where(Docente.usuario_id == u.id))
        if d:
            out.update(programa_id=d.programa_id, numero_empleado=d.numero_empleado, especialidad=d.especialidad,
                       titulo_postgrado=d.titulo_postgrado)
    elif rol == Rol.COORDINADOR:
        c = db.scalar(select(CoordinadorPrograma).where(CoordinadorPrograma.usuario_id == u.id))
        ids = [int(x) for x in (c.programa_responsable_ids or [])] if c else []
        out.update(programas_ids=ids, programa_id=ids[0] if ids else None)
    elif rol == Rol.BIENESTAR:
        b = db.scalar(select(PersonalBienestar).where(PersonalBienestar.usuario_id == u.id))
        if b:
            out.update(profesion=b.profesion, especializacion=b.especializacion)
    elif rol == Rol.ADMIN:
        a = db.scalar(select(PersonalAdministrativo).where(PersonalAdministrativo.usuario_id == u.id))
        if a:
            out.update(cargo_administrativo=a.cargo_administrativo, area_responsable=a.area_responsable)
    return out


def _out(db: Session, u: Usuario) -> dict:
    pendiente = str(u.estado) in (EstadoUsuario.PENDIENTE_ACTIVACION, EstadoUsuario.PENDIENTE_CONSENTIMIENTO) and not u.password_hash
    return {
        "id": u.id, "email": u.email, "nombre_completo": u.nombre_completo, "rol": str(u.rol), "estado": str(u.estado),
        "numero_documento": u.numero_documento, "tipo_documento": str(u.tipo_documento) if u.tipo_documento else None,
        "telefono": u.telefono, "created_at": u.created_at, "fecha_ultima_sesion": u.fecha_ultima_sesion,
        "invitacion_pendiente": pendiente,
        "invitacion_vencida": bool(pendiente and (u.activation_token_hash is None or (
            u.activation_expires_at is not None and u.activation_expires_at <= utcnow()))),
        **_perfil_dict(db, u),
    }


def _get_user(db: Session, uid: int) -> Usuario:
    u = db.get(Usuario, uid)
    if u is None:
        raise NotFound("No encontramos a ese usuario.", "USUARIO_NO_ENCONTRADO")
    return u


def _assert_manage(actor: Usuario, target: Usuario, *, solo_admin: bool = False, permite_estudiante: bool = False) -> None:
    if str(actor.rol) == Rol.ADMIN:
        return
    if solo_admin or str(target.rol) not in (Rol.DOCENTE, Rol.ESTUDIANTE if permite_estudiante else Rol.DOCENTE):
        raise Forbidden("Bienestar solo puede gestionar cuentas de docentes. Pida al administrador este cambio.", "ROL_NO_PERMITIDO")


def _check_programas(db: Session, ids: list[int]) -> None:
    for pid in ids:
        if db.get(ProgramaAcademico, pid) is None:
            raise Unprocessable(f"El programa {pid} no existe.", "PROGRAMA_INVALIDO")


def _perfil_kwargs(rol: Rol, body) -> dict:
    campos = {
        Rol.DOCENTE: ("programa_id", "numero_empleado", "titulo_postgrado", "especialidad"),
        Rol.BIENESTAR: ("profesion", "especializacion"),
        Rol.ADMIN: ("cargo_administrativo", "area_responsable"),
    }.get(rol, ())
    out = {c: getattr(body, c) for c in campos if getattr(body, c, None) is not None}
    if rol == Rol.COORDINADOR and body.programas_ids is not None:
        out["programa_responsable_ids"] = list(body.programas_ids)
    return out


# ----------------------------------------------------------------------------- programas (antes de /{id})
@router.get("/programas")
def listar_programas(db: Session = Depends(get_db), _=LECTORES_PROG):
    rows = db.scalars(select(ProgramaAcademico).order_by(ProgramaAcademico.nombre_programa)).all()
    return {"items": [_programa_out(p) for p in rows]}


def _programa_out(p: ProgramaAcademico) -> dict:
    return {
        "id": p.id, "nombre_programa": p.nombre_programa, "codigo_programa": p.codigo_programa,
        "descripcion_programa": p.descripcion_programa, "nivel_academico": str(p.nivel_academico),
        "duracion_semestres": p.duracion_semestres, "total_creditos": p.total_creditos,
        "facultad_responsable": p.facultad_responsable, "semestre_practicas": p.semestre_practicas,
        "disponibilidad_ajustes_tea": p.disponibilidad_ajustes_tea, "capacitacion_docentes_tea": p.capacitacion_docentes_tea,
        "coordinador_programa_id": p.coordinador_programa_id,
    }


def _coordinador_id(db: Session, usuario_id: int | None) -> int | None:
    if usuario_id is None:
        return None
    c = db.scalar(select(CoordinadorPrograma).where(CoordinadorPrograma.usuario_id == usuario_id))
    if c is None:
        raise Unprocessable("Ese usuario no es un coordinador.", "COORDINADOR_INVALIDO")
    return c.id


@router.post("/programas", status_code=201)
def crear_programa(body: ProgramaCreate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    if db.scalar(select(ProgramaAcademico.id).where(ProgramaAcademico.codigo_programa == body.codigo_programa)
                 .execution_options(include_deleted=True)):
        raise Conflict("Ya existe un programa con ese código.", "PROGRAMA_DUPLICADO")
    datos = body.model_dump(exclude={"coordinador_usuario_id"})
    p = ProgramaAcademico(**datos, coordinador_programa_id=_coordinador_id(db, body.coordinador_usuario_id))
    db.add(p)
    db.flush()
    audit.log(db, admin, "PROGRAMA_CREADO", "programa_academico", p.id, {"codigo": p.codigo_programa}, request=request)
    db.commit()
    return _programa_out(p)


@router.patch("/programas/{programa_id}")
def editar_programa(programa_id: int, body: ProgramaUpdate, request: Request, db: Session = Depends(get_db),
                    admin: Usuario = ADMIN):
    p = db.get(ProgramaAcademico, programa_id)
    if p is None:
        raise NotFound("No encontramos ese programa.", "PROGRAMA_NO_ENCONTRADO")
    cambios = body.model_dump(exclude_unset=True)
    if "codigo_programa" in cambios and cambios["codigo_programa"] != p.codigo_programa and db.scalar(
        select(ProgramaAcademico.id).where(ProgramaAcademico.codigo_programa == cambios["codigo_programa"])
        .execution_options(include_deleted=True)
    ):
        raise Conflict("Ya existe un programa con ese código.", "PROGRAMA_DUPLICADO")
    if "coordinador_usuario_id" in cambios:
        p.coordinador_programa_id = _coordinador_id(db, cambios.pop("coordinador_usuario_id"))
    for k, v in cambios.items():
        setattr(p, k, v)
    audit.log(db, admin, "PROGRAMA_MODIFICADO", "programa_academico", p.id, {"campos": sorted(cambios)}, request=request)
    db.commit()
    return _programa_out(p)


@router.delete("/programas/{programa_id}", status_code=204)
def archivar_programa(programa_id: int, request: Request, body: MotivoBody | None = None,
                      db: Session = Depends(get_db), admin: Usuario = ADMIN):
    p = db.get(ProgramaAcademico, programa_id)
    if p is None:
        raise NotFound("No encontramos ese programa.", "PROGRAMA_NO_ENCONTRADO")
    en_uso = (
        db.scalar(select(func.count()).select_from(Estudiante).where(Estudiante.programa_id == p.id))
        or db.scalar(select(func.count()).select_from(Docente).where(Docente.programa_id == p.id))
        or db.scalar(select(func.count()).select_from(Asignatura).where(Asignatura.programa_id == p.id))
    )
    if en_uso:
        raise Conflict("El programa tiene estudiantes, docentes o asignaturas. Muévalos antes de archivarlo.", "PROGRAMA_EN_USO")
    p.soft_delete(admin.id, (body.motivo if body else None) or "Archivado por el administrador")
    audit.log(db, admin, "PROGRAMA_ARCHIVADO", "programa_academico", p.id, request=request)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------------------- asignaturas
def _asig_out(a: Asignatura) -> dict:
    return {"id": a.id, "programa_id": a.programa_id, "codigo": a.codigo, "nombre": a.nombre, "semestre_plan": a.semestre_plan,
            "creditos": a.creditos, "escenario_predominante": str(a.escenario_predominante) if a.escenario_predominante else None,
            "es_practica": a.es_practica}


@router.get("/asignaturas")
def listar_asignaturas(programa_id: int | None = None, q: str | None = None, params: PageParams = Depends(),
                       db: Session = Depends(get_db), _=ADMIN_BIENESTAR):
    stmt = select(Asignatura).order_by(Asignatura.programa_id, Asignatura.codigo)
    if programa_id:
        stmt = stmt.where(Asignatura.programa_id == programa_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Asignatura.nombre).like(like), func.lower(Asignatura.codigo).like(like)))
    return paginate(db, stmt, params, _asig_out)


@router.post("/asignaturas", status_code=201)
def crear_asignatura(body: AsignaturaCreate, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    if db.get(ProgramaAcademico, body.programa_id) is None:
        raise Unprocessable("El programa indicado no existe.", "PROGRAMA_INVALIDO")
    if db.scalar(select(Asignatura.id).where(Asignatura.programa_id == body.programa_id, Asignatura.codigo == body.codigo)):
        raise Conflict("Ya existe una asignatura con ese código en el programa.", "ASIGNATURA_DUPLICADA")
    a = Asignatura(**body.model_dump())
    db.add(a)
    db.flush()
    audit.log(db, admin, "ASIGNATURA_CREADA", "asignatura", a.id, {"codigo": a.codigo}, request=request)
    db.commit()
    return _asig_out(a)


def _get_asig(db: Session, aid: int) -> Asignatura:
    a = db.get(Asignatura, aid)
    if a is None:
        raise NotFound("No encontramos esa asignatura.", "ASIGNATURA_NO_ENCONTRADA")
    return a


@router.patch("/asignaturas/{asignatura_id}")
def editar_asignatura(asignatura_id: int, body: AsignaturaUpdate, request: Request, db: Session = Depends(get_db),
                      admin: Usuario = ADMIN):
    a = _get_asig(db, asignatura_id)
    cambios = body.model_dump(exclude_unset=True)
    if "codigo" in cambios and cambios["codigo"] != a.codigo and db.scalar(
        select(Asignatura.id).where(Asignatura.programa_id == a.programa_id, Asignatura.codigo == cambios["codigo"])
    ):
        raise Conflict("Ya existe una asignatura con ese código en el programa.", "ASIGNATURA_DUPLICADA")
    for k, v in cambios.items():
        setattr(a, k, v)
    audit.log(db, admin, "ASIGNATURA_MODIFICADA", "asignatura", a.id, {"campos": sorted(cambios)}, request=request)
    db.commit()
    return _asig_out(a)


@router.delete("/asignaturas/{asignatura_id}", status_code=204)
def archivar_asignatura(asignatura_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = ADMIN):
    a = _get_asig(db, asignatura_id)
    if db.scalar(select(func.count()).select_from(AsignacionDocente).where(AsignacionDocente.asignatura_id == a.id)):
        raise Conflict("La asignatura tiene docentes asignados. Quite las asignaciones antes de archivarla.", "ASIGNATURA_EN_USO")
    a.soft_delete(admin.id, "Archivada por el administrador")
    audit.log(db, admin, "ASIGNATURA_ARCHIVADA", "asignatura", a.id, request=request)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------------------- Vía 1
@router.post("/estudiantes", status_code=201)
def crear_estudiante_via1(body: EstudianteVia1, request: Request, db: Session = Depends(get_db),
                          actor: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ADMIN))):
    """Vía 1: Bienestar crea la cuenta con consentimiento verbal declarado. Invitación de 72 h; el F0 sigue siendo obligatorio."""
    # Si es correo personal (ej. primer semestre sin correo institucional), se permite
    es_personal = body.es_correo_personal or (body.tipo_correo and body.tipo_correo.upper() == "PERSONAL")
    if not es_personal:
        student_intake.validar_email_institucional(body.email)

    student_intake.get_programa_or_422(db, body.programa_id)
    identificacion = (body.cedula or body.codigo_estudiante or "").strip()
    user, est = student_intake.create_student_account(
        db, nombre_completo=body.nombre_completo, email=body.email, codigo=identificacion,
        programa_id=body.programa_id, via=ViaIngreso.BIENESTAR, estado=EstadoUsuario.PENDIENTE_ACTIVACION,
        telefono=body.telefono, semestre_actual=body.semestre_actual,
        bienestar_asignado_id=actor.id if str(actor.rol) == Rol.BIENESTAR else None,
    )
    user.numero_documento = identificacion
    invite_user(db, user, actor=actor, request=request, extra={"rol": "ESTUDIANTE"})
    audit.log(db, actor, "ESTUDIANTE_CREADO_VIA1", "estudiante", est.id,
              {"consentimiento_verbal_declarado": True, "programa_id": body.programa_id, "cedula": identificacion,
               "tipo_correo": "PERSONAL" if es_personal else "INSTITUCIONAL"},
              request=request, estudiante_id=est.id)
    db.commit()
    tipo_msg = "personal" if es_personal else "institucional"
    return {**_out(db, user), "estudiante_id": est.id,
            "detail": f"Cuenta creada. Enviamos la invitación al correo {tipo_msg} (vale 72 horas). El estudiante deberá firmar el consentimiento (F0) al ingresar."}


# ----------------------------------------------------------------------------- CRUD de cuentas
@router.get("")
def listar_usuarios(
    rol: Rol | None = None, estado: EstadoUsuario | None = None, q: str | None = None, programa_id: int | None = None,
    params: PageParams = Depends(), db: Session = Depends(get_db), actor: Usuario = ADMIN_BIENESTAR,
):
    stmt = select(Usuario).order_by(Usuario.nombre_completo)
    if str(actor.rol) == Rol.BIENESTAR:
        if rol not in (None, Rol.DOCENTE):
            raise Forbidden("Bienestar solo puede consultar cuentas de docentes.", "ROL_NO_PERMITIDO")
        rol = Rol.DOCENTE
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    if estado:
        stmt = stmt.where(Usuario.estado == estado)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Usuario.nombre_completo).like(like), func.lower(Usuario.email).like(like),
                              Usuario.numero_documento.like(f"%{q.strip()}%")))
    if programa_id:
        stmt = stmt.where(or_(
            Usuario.id.in_(select(Docente.usuario_id).where(Docente.programa_id == programa_id)),
            Usuario.id.in_(select(Estudiante.usuario_id).where(Estudiante.programa_id == programa_id)),
        ))
    return paginate(db, stmt, params, lambda u: _out(db, u))


@router.post("", status_code=201)
def crear_usuario(body: UsuarioCreate, request: Request, db: Session = Depends(get_db), actor: Usuario = ADMIN_BIENESTAR):
    if str(actor.rol) == Rol.BIENESTAR and body.rol != Rol.DOCENTE:
        raise Forbidden("Bienestar solo puede crear cuentas de docentes.", "ROL_NO_PERMITIDO")
    email = normalize_email(body.email)
    if student_intake.email_taken(db, email):
        raise Conflict("Ya existe una cuenta (o archivada) con ese correo electrónico.", "EMAIL_DUPLICADO")
    if body.numero_documento and db.scalar(select(Usuario.id).where(Usuario.numero_documento == body.numero_documento)
                                           .execution_options(include_deleted=True)):
        raise Conflict("Ya existe una cuenta con ese número de documento.", "DOCUMENTO_DUPLICADO")
    pids = ([body.programa_id] if body.programa_id else []) + list(body.programas_ids or [])
    _check_programas(db, pids)
    user = create_user(db, email=email, nombre_completo=body.nombre_completo, rol=body.rol,
                       numero_documento=body.numero_documento, tipo_documento=body.tipo_documento, telefono=body.telefono,
                       perfil=_perfil_kwargs(body.rol, body))
    invite_user(db, user, actor=actor, request=request)
    db.commit()
    return _out(db, user)


@router.get("/{usuario_id}")
def ver_usuario(usuario_id: int, db: Session = Depends(get_db), actor: Usuario = ADMIN_BIENESTAR):
    u = _get_user(db, usuario_id)
    _assert_manage(actor, u)
    out = _out(db, u)
    if str(u.rol) == Rol.DOCENTE:
        out["asignaciones"] = _asignaciones(db, u)
    return out


@router.patch("/{usuario_id}")
def editar_usuario(usuario_id: int, body: UsuarioUpdate, request: Request, db: Session = Depends(get_db),
                   actor: Usuario = ADMIN_BIENESTAR):
    u = _get_user(db, usuario_id)
    _assert_manage(actor, u)
    cambios = body.model_dump(exclude_unset=True)
    if "email" in cambios and cambios["email"]:
        nuevo = normalize_email(cambios["email"])
        if nuevo != u.email:
            if student_intake.email_taken(db, nuevo):
                raise Conflict("Ya existe una cuenta con ese correo electrónico.", "EMAIL_DUPLICADO")
            u.email = nuevo
            revoke_all_user_tokens(db, u.id)
    if "numero_documento" in cambios and cambios["numero_documento"] != u.numero_documento and cambios["numero_documento"]:
        if db.scalar(select(Usuario.id).where(Usuario.numero_documento == cambios["numero_documento"], Usuario.id != u.id)
                     .execution_options(include_deleted=True)):
            raise Conflict("Ya existe una cuenta con ese número de documento.", "DOCUMENTO_DUPLICADO")
    for campo in ("nombre_completo", "numero_documento", "tipo_documento", "telefono"):
        if campo in cambios:
            setattr(u, campo, cambios[campo])
    pids = ([body.programa_id] if body.programa_id else []) + list(body.programas_ids or [])
    _check_programas(db, pids)
    rol = Rol(str(u.rol))
    kw = _perfil_kwargs(rol, body)
    if rol == Rol.DOCENTE and kw:
        d = db.scalar(select(Docente).where(Docente.usuario_id == u.id))
        for k, v in kw.items():
            setattr(d, k, v)
    elif rol == Rol.COORDINADOR and kw:
        c = db.scalar(select(CoordinadorPrograma).where(CoordinadorPrograma.usuario_id == u.id))
        c.programa_responsable_ids = kw["programa_responsable_ids"]
    elif rol == Rol.BIENESTAR and kw:
        b = db.scalar(select(PersonalBienestar).where(PersonalBienestar.usuario_id == u.id))
        for k, v in kw.items():
            setattr(b, k, v)
    elif rol == Rol.ADMIN and kw:
        a = db.scalar(select(PersonalAdministrativo).where(PersonalAdministrativo.usuario_id == u.id))
        for k, v in kw.items():
            setattr(a, k, v)
    audit.log(db, actor, audit.Accion.USUARIO_MODIFICADO, "usuario", u.id, {"campos": sorted(cambios)}, request=request)
    db.commit()
    return _out(db, u)


def _guard_ultimo_admin(db: Session, u: Usuario, actor: Usuario) -> None:
    if u.id == actor.id:
        raise Conflict("No puede desactivar o archivar su propia cuenta.", "AUTO_DESACTIVACION")
    if str(u.rol) == Rol.ADMIN and (db.scalar(select(func.count()).select_from(Usuario).where(
            Usuario.rol == Rol.ADMIN, Usuario.estado == EstadoUsuario.ACTIVO, Usuario.id != u.id)) or 0) == 0:
        raise Conflict("Debe quedar al menos un administrador activo.", "ULTIMO_ADMIN")


@router.post("/{usuario_id}/desactivar")
def desactivar(usuario_id: int, request: Request, body: MotivoBody | None = None, db: Session = Depends(get_db),
               actor: Usuario = ADMIN):
    u = _get_user(db, usuario_id)
    _guard_ultimo_admin(db, u, actor)
    if str(u.estado) == EstadoUsuario.INACTIVO:
        raise Conflict("La cuenta ya está inactiva.", "CUENTA_YA_INACTIVA")
    u.estado = EstadoUsuario.INACTIVO
    u.activation_token_hash = None
    revoke_all_user_tokens(db, u.id)
    audit.log(db, actor, audit.Accion.USUARIO_MODIFICADO, "usuario", u.id,
              {"accion": "DESACTIVADO", "motivo": (body.motivo if body else None)}, request=request)
    db.commit()
    return _out(db, u)


@router.post("/{usuario_id}/reactivar")
def reactivar(usuario_id: int, request: Request, db: Session = Depends(get_db), actor: Usuario = ADMIN):
    u = _get_user(db, usuario_id)
    if str(u.estado) != EstadoUsuario.INACTIVO:
        raise Conflict("Solo se pueden reactivar cuentas inactivas.", "CUENTA_NO_INACTIVA")
    if not u.password_hash:
        u.estado = EstadoUsuario.PENDIENTE_ACTIVACION
        invite_user(db, u, actor=actor, request=request)
    elif str(u.rol) == Rol.ESTUDIANTE:
        from app.core.permissions import user_has_consent

        u.estado = EstadoUsuario.ACTIVO if user_has_consent(db, u) else EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    else:
        u.estado = EstadoUsuario.ACTIVO
    audit.log(db, actor, audit.Accion.USUARIO_MODIFICADO, "usuario", u.id, {"accion": "REACTIVADO"}, request=request)
    db.commit()
    return _out(db, u)


@router.delete("/{usuario_id}", status_code=204)
def archivar_usuario(usuario_id: int, request: Request, body: MotivoBody | None = None, db: Session = Depends(get_db),
                     actor: Usuario = ADMIN):
    """Baja lógica (soft delete): la cuenta deja de aparecer y de poder ingresar; el correo queda reservado."""
    u = _get_user(db, usuario_id)
    _guard_ultimo_admin(db, u, actor)
    u.estado = EstadoUsuario.INACTIVO
    revoke_all_user_tokens(db, u.id)
    u.soft_delete(actor.id, (body.motivo if body else None) or "Archivado por el administrador")
    audit.log(db, actor, audit.Accion.USUARIO_MODIFICADO, "usuario", u.id, {"accion": "ARCHIVADO"}, request=request)
    db.commit()
    return Response(status_code=204)


@router.post("/{usuario_id}/reenviar-invitacion")
def reenviar_invitacion(usuario_id: int, request: Request, db: Session = Depends(get_db), actor: Usuario = ADMIN_BIENESTAR):
    u = _get_user(db, usuario_id)
    _assert_manage(actor, u, permite_estudiante=True)
    if str(u.rol) == Rol.FAMILIAR:
        raise Forbidden("Las invitaciones de familiares las gestiona el propio estudiante.", "ROL_NO_PERMITIDO")
    student_intake.resend_invitation(db, u, actor=actor, request=request)
    db.commit()
    return {"detail": "Enviamos una nueva invitación (vale 72 horas).", **_out(db, u)}


# ----------------------------------------------------------------------------- docentes: asignaciones
def _asignaciones(db: Session, u: Usuario) -> list[dict]:
    d = db.scalar(select(Docente).where(Docente.usuario_id == u.id))
    if d is None:
        return []
    rows = db.execute(
        select(AsignacionDocente, Asignatura).join(Asignatura, Asignatura.id == AsignacionDocente.asignatura_id)
        .where(AsignacionDocente.docente_id == d.id).order_by(AsignacionDocente.semestre_academico.desc(), Asignatura.codigo)
    ).all()
    return [{"id": a.id, "asignatura_id": s.id, "asignatura_codigo": s.codigo, "asignatura_nombre": s.nombre,
             "semestre_academico": a.semestre_academico, "grupo": a.grupo} for a, s in rows]


def _docente_or_422(db: Session, actor: Usuario, uid: int) -> tuple[Usuario, Docente]:
    u = _get_user(db, uid)
    _assert_manage(actor, u)
    d = db.scalar(select(Docente).where(Docente.usuario_id == u.id)) if str(u.rol) == Rol.DOCENTE else None
    if d is None:
        raise Unprocessable("Esa cuenta no es de un docente.", "NO_ES_DOCENTE")
    return u, d


@router.get("/{usuario_id}/asignaciones")
def listar_asignaciones(usuario_id: int, db: Session = Depends(get_db), actor: Usuario = ADMIN_BIENESTAR):
    u, _ = _docente_or_422(db, actor, usuario_id)
    return {"items": _asignaciones(db, u)}


@router.post("/{usuario_id}/asignaciones", status_code=201)
def asignar(usuario_id: int, body: AsignacionCreate, request: Request, db: Session = Depends(get_db),
            actor: Usuario = ADMIN_BIENESTAR):
    u, d = _docente_or_422(db, actor, usuario_id)
    _get_asig(db, body.asignatura_id)
    if db.scalar(select(AsignacionDocente.id).where(
        AsignacionDocente.docente_id == d.id, AsignacionDocente.asignatura_id == body.asignatura_id,
        AsignacionDocente.semestre_academico == body.semestre_academico,
        AsignacionDocente.grupo.is_(None) if body.grupo is None else AsignacionDocente.grupo == body.grupo,
    )):
        raise Conflict("El docente ya está asignado a esa asignatura en ese semestre y grupo.", "ASIGNACION_DUPLICADA")
    a = AsignacionDocente(docente_id=d.id, **body.model_dump())
    db.add(a)
    db.flush()
    audit.log(db, actor, "ASIGNACION_DOCENTE_CREADA", "asignacion_docente", a.id,
              {"docente_usuario_id": u.id, "asignatura_id": body.asignatura_id}, request=request)
    db.commit()
    return {"items": _asignaciones(db, u)}


@router.delete("/{usuario_id}/asignaciones/{asignacion_id}", status_code=204)
def quitar_asignacion(usuario_id: int, asignacion_id: int, request: Request, db: Session = Depends(get_db),
                      actor: Usuario = ADMIN_BIENESTAR):
    u, d = _docente_or_422(db, actor, usuario_id)
    a = db.get(AsignacionDocente, asignacion_id)
    if a is None or a.docente_id != d.id:
        raise NotFound("No encontramos esa asignación.", "ASIGNACION_NO_ENCONTRADA")
    a.soft_delete(actor.id, "Asignación retirada")
    audit.log(db, actor, "ASIGNACION_DOCENTE_RETIRADA", "asignacion_docente", a.id, {"docente_usuario_id": u.id}, request=request)
    db.commit()
    return Response(status_code=204)

