"""Autenticación: login, refresh (rotación), logout, activación, recuperación, `/me`, preferencias y SSO.

OWNER: base (completo). Contrato con el frontend en `docs/api/auth.md`.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import AppError, Conflict, Forbidden, Locked, Unauthorized
from app.core.permissions import user_has_consent
from app.core.ratelimit import check_rate_limit, login_rate_limit
from app.core.security import (
    assert_not_locked,
    clear_refresh_cookie,
    create_access_token,
    create_reset_token,
    find_user_by_activation_token,
    find_user_by_reset_token,
    hash_password,
    hash_token,
    issue_recovery_code,
    issue_refresh_token,
    password_needs_rehash,
    register_failed_login,
    reset_failed_logins,
    revoke_all_user_tokens,
    revoke_family,
    rotate_refresh_token,
    set_refresh_cookie,
    validate_password_strength,
    verify_password,
    verify_recovery_code,
)
from app.models.base import utcnow
from app.models.consentimiento import AutorizacionFamiliar
from app.models.enums import EstadoAutorizacionFamiliar, EstadoUsuario, Rol
from app.models.usuarios import CoordinadorPrograma, Docente, Estudiante, PreferenciaSensorialUI, RefreshToken, Usuario
from app.schemas.auth import (
    ActivateRequest,
    ActivateResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    Me,
    PreferenciasUI,
    PreferenciasUIUpdate,
    RecoverRequest,
    RecoverResponse,
    RecoveryCodeResponse,
    RegenerateRecoveryRequest,
    RegisterRequest,
    RegisterResponse,
    RegistroOpciones,
    ResetPasswordRequest,
)
from app.schemas.common import MessageResponse
from app.services import accounts, sso
from app.services.notifications import Evento, notify

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_LOGIN_ERROR = "Correo o contraseña incorrectos. Revise sus datos e intente de nuevo."
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


# ----------------------------------------------------------------------------- helpers
def _programa_id(db: Session, user: Usuario) -> int | None:
    rol = str(user.rol)
    if rol == Rol.ESTUDIANTE:
        return db.scalar(select(Estudiante.programa_id).where(Estudiante.usuario_id == user.id))
    if rol == Rol.DOCENTE:
        return db.scalar(select(Docente.programa_id).where(Docente.usuario_id == user.id))
    if rol == Rol.COORDINADOR:
        coord = db.scalar(select(CoordinadorPrograma).where(CoordinadorPrograma.usuario_id == user.id))
        ids = (coord.programa_responsable_ids or []) if coord else []
        return int(ids[0]) if ids else None
    return None


def prefs_of(db: Session, user: Usuario) -> PreferenciasUI:
    p = db.scalar(select(PreferenciaSensorialUI).where(PreferenciaSensorialUI.usuario_id == user.id))
    return PreferenciasUI.model_validate(p) if p else PreferenciasUI()


def build_me(db: Session, user: Usuario) -> Me:
    """`{id,email,nombre_completo,rol,estado,consentimiento_firmado,programa_id,preferencias_ui}`."""
    return Me(
        id=user.id,
        email=user.email,
        nombre_completo=user.nombre_completo,
        rol=str(user.rol),
        estado=str(user.estado),
        consentimiento_firmado=user_has_consent(db, user),
        programa_id=_programa_id(db, user),
        preferencias_ui=prefs_of(db, user),
    )


def _session_response(db: Session, user: Usuario, request: Request, response: Response, family_id: str | None = None,
                      raw_refresh: str | None = None) -> LoginResponse:
    token, expires_in = create_access_token(user)
    if raw_refresh is None:
        raw_refresh, _ = issue_refresh_token(
            db, user, family_id=family_id, ip=audit.client_ip(request), user_agent=request.headers.get("user-agent")
        )
    set_refresh_cookie(response, raw_refresh)
    return LoginResponse(access_token=token, token_type="bearer", expires_in=expires_in, user=build_me(db, user))


def _check_estado_for_login(user: Usuario) -> None:
    estado = str(user.estado)
    if estado == EstadoUsuario.PENDIENTE_ACTIVACION:
        raise Forbidden("Su cuenta aún no está activada. Use el enlace de activación que le entregaron o pida a "
                        "Bienestar que le restablezca el acceso.", "CUENTA_NO_ACTIVADA")
    if estado in (EstadoUsuario.INACTIVO, EstadoUsuario.SUSPENDIDO):
        raise Forbidden("Su cuenta está inactiva. Comuníquese con el administrador o con Bienestar.", "CUENTA_INACTIVA")


# ----------------------------------------------------------------------------- login / refresh / logout
@router.post("/login", response_model=LoginResponse, dependencies=[Depends(login_rate_limit)])
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(Usuario).where(Usuario.email == email))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)  # iguala tiempos de respuesta
        audit.log(db, None, audit.Accion.LOGIN_FALLIDO, "usuario", None, {"motivo": "usuario_desconocido"},
                  request=request, commit=True)
        raise Unauthorized(_GENERIC_LOGIN_ERROR, "CREDENCIALES_INVALIDAS")

    try:
        assert_not_locked(user)
    except Locked:
        audit.log(db, user, audit.Accion.LOGIN_FALLIDO, "usuario", user.id, {"motivo": "cuenta_bloqueada"},
                  request=request, commit=True)
        raise

    if not verify_password(body.password, user.password_hash):
        locked_now = register_failed_login(user)
        audit.log(db, user, audit.Accion.LOGIN_FALLIDO, "usuario", user.id,
                  {"intentos": user.failed_attempts}, request=request)
        if locked_now:
            audit.log(db, user, audit.Accion.LOGIN_BLOQUEO, "usuario", user.id,
                      {"hasta": user.locked_until.isoformat()}, request=request)
        db.commit()
        if locked_now:
            assert_not_locked(user)  # lanza 423 con minutos restantes
        raise Unauthorized(_GENERIC_LOGIN_ERROR, "CREDENCIALES_INVALIDAS")

    _check_estado_for_login(user)
    reset_failed_logins(user)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.fecha_ultima_sesion = utcnow()
    result = _session_response(db, user, request, response)
    audit.log(db, user, audit.Accion.LOGIN_OK, "usuario", user.id, request=request)
    db.commit()
    return result


@router.post("/refresh", response_model=LoginResponse, dependencies=[Depends(login_rate_limit)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db),
            sti_refresh: str | None = Cookie(default=None, alias=get_settings().refresh_cookie_name)):
    """Rota el refresh token (cookie HttpOnly) y devuelve un nuevo access token + usuario."""
    try:
        user, new_raw = rotate_refresh_token(db, sti_refresh, ip=audit.client_ip(request),
                                             user_agent=request.headers.get("user-agent"))
    except Unauthorized:
        clear_refresh_cookie(response)
        raise
    result = _session_response(db, user, request, response, raw_refresh=new_raw)
    db.commit()
    return result


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response, db: Session = Depends(get_db),
           sti_refresh: str | None = Cookie(default=None, alias=get_settings().refresh_cookie_name)):
    actor = None
    if sti_refresh:
        rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(sti_refresh)))
        if rt is not None:
            revoke_family(db, rt.family_id)
            actor = db.get(Usuario, rt.usuario_id)
    if actor is not None:
        audit.log(db, actor, audit.Accion.LOGOUT, "usuario", actor.id, request=request)
    db.commit()
    clear_refresh_cookie(response)
    return MessageResponse(detail="Sesión cerrada.")


# ----------------------------------------------------------------------------- registro autónomo (sin correo)
@router.get("/registro/opciones", response_model=RegistroOpciones)
def registro_opciones():
    s = get_settings()
    return RegistroOpciones(registro_abierto=s.registro_abierto, roles=accounts.registro_roles_disponibles(),
                            requiere_codigo_personal=[str(r) for r in accounts.ROLES_REGISTRO_CON_CODIGO],
                            min_password_length=s.min_password_length)


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Crea la cuenta al instante (sin verificar el correo), abre sesión y entrega el código de recuperación."""
    ip = audit.client_ip(request) or "desconocida"
    check_rate_limit(f"registro:{ip}", get_settings().registro_rate_limit_per_hour, 3600)
    if not body.acepta_aviso_privacidad:
        raise AppError("Debe aceptar el aviso de privacidad para crear su cuenta.", "AVISO_PRIVACIDAD_REQUERIDO",
                       status_code=422)
    user, codigo = accounts.register_self(
        db, rol=body.rol, email=body.email, nombre_completo=body.nombre_completo, password=body.password,
        telefono=body.telefono, codigo_estudiante=body.codigo_estudiante, programa_id=body.programa_id,
        codigo_acceso=body.codigo_acceso, codigo_vinculacion=body.codigo_vinculacion, request=request)
    user.fecha_ultima_sesion = utcnow()
    session = _session_response(db, user, request, response)
    audit.log(db, user, audit.Accion.LOGIN_OK, "usuario", user.id, {"via": "registro"}, request=request)
    db.commit()
    return RegisterResponse(**session.model_dump(), codigo_recuperacion=codigo)


@router.post("/recover", response_model=RecoverResponse, dependencies=[Depends(login_rate_limit)])
def recover(body: RecoverRequest, request: Request, db: Session = Depends(get_db)):
    """Restablece la contraseña con el código de recuperación (sin correo). Entrega un código nuevo."""
    err = AppError("El correo o el código de recuperación no son correctos. Revíselos o pida a Bienestar que le "
                   "restablezca el acceso.", "CODIGO_RECUPERACION_INVALIDO", status_code=400)
    user = db.scalar(select(Usuario).where(Usuario.email == body.email.strip().lower()))
    if user is None or str(user.estado) in (EstadoUsuario.INACTIVO, EstadoUsuario.SUSPENDIDO):
        verify_password("x", _DUMMY_HASH)
        raise err
    assert_not_locked(user)
    if not verify_recovery_code(user, body.codigo_recuperacion):
        locked_now = register_failed_login(user)
        audit.log(db, user, audit.Accion.LOGIN_FALLIDO, "usuario", user.id, {"motivo": "codigo_recuperacion"},
                  request=request)
        db.commit()
        if locked_now:
            assert_not_locked(user)
        raise err
    validate_password_strength(body.password)
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    user.reset_token_hash = None
    user.reset_expires_at = None
    reset_failed_logins(user)
    if str(user.estado) == EstadoUsuario.PENDIENTE_ACTIVACION:
        user.estado = accounts._estado_tras_acceso(db, user)
    revoke_all_user_tokens(db, user.id)
    nuevo = issue_recovery_code(user)
    audit.log(db, user, audit.Accion.CONTRASENA_RESTABLECIDA, "usuario", user.id, {"via": "codigo_recuperacion"},
              request=request)
    db.commit()
    return RecoverResponse(detail="Su contraseña fue restablecida. Guarde su nuevo código de recuperación.",
                           codigo_recuperacion=nuevo)


@router.post("/recovery-code/regenerate", response_model=RecoveryCodeResponse)
def regenerate_recovery_code(body: RegenerateRecoveryRequest, request: Request,
                             user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """Genera un código de recuperación nuevo (el anterior deja de servir). Pide la contraseña actual."""
    if not verify_password(body.password, user.password_hash):
        raise AppError("La contraseña no es correcta.", "CONTRASENA_ACTUAL_INCORRECTA", status_code=400)
    codigo = issue_recovery_code(user)
    audit.log(db, user, "CODIGO_RECUPERACION_REGENERADO", "usuario", user.id, request=request)
    db.commit()
    return RecoveryCodeResponse(detail="Generamos un código nuevo. Guárdelo: no se vuelve a mostrar.",
                                codigo_recuperacion=codigo)


# ----------------------------------------------------------------------------- activación / recuperación
@router.post("/activate", response_model=ActivateResponse, dependencies=[Depends(login_rate_limit)])
def activate(body: ActivateRequest, request: Request, db: Session = Depends(get_db)):
    user = find_user_by_activation_token(db, body.token)
    if str(user.estado) not in (EstadoUsuario.PENDIENTE_ACTIVACION, EstadoUsuario.PENDIENTE_CONSENTIMIENTO):
        raise Conflict("Esta cuenta ya fue activada. Inicie sesión con su correo y contraseña.", "CUENTA_YA_ACTIVADA")
    validate_password_strength(body.password)
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    user.activation_token_hash = None
    user.activation_expires_at = None
    reset_failed_logins(user)
    if str(user.rol) == Rol.ESTUDIANTE:
        # Estudiante: ACTIVO solo cuando firme F0 (RF-05); mientras tanto PENDIENTE_CONSENTIMIENTO
        user.estado = EstadoUsuario.ACTIVO if user_has_consent(db, user) else EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    else:
        user.estado = EstadoUsuario.ACTIVO
    if str(user.rol) == Rol.FAMILIAR:
        for a in db.scalars(
            select(AutorizacionFamiliar).where(
                AutorizacionFamiliar.familiar_email == user.email,
                AutorizacionFamiliar.estado == EstadoAutorizacionFamiliar.PENDIENTE,
            )
        ):
            a.familiar_usuario_id = user.id
            a.estado = EstadoAutorizacionFamiliar.VIGENTE
    audit.log(db, user, audit.Accion.ACTIVACION_CUENTA, "usuario", user.id, request=request)
    db.commit()
    return ActivateResponse(detail="Su cuenta fue activada. Ya puede iniciar sesión.", email=user.email,
                            estado=str(user.estado))


@router.post("/forgot-password", response_model=MessageResponse, dependencies=[Depends(login_rate_limit)])
def forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Siempre responde igual (no revela si el correo existe)."""
    s = get_settings()
    user = db.scalar(select(Usuario).where(Usuario.email == body.email.strip().lower()))
    if user is not None and user.password_hash and str(user.estado) in (
        EstadoUsuario.ACTIVO, EstadoUsuario.PENDIENTE_CONSENTIMIENTO
    ):
        raw = create_reset_token(user)
        enlace = f"{s.frontend_url.rstrip('/')}{s.reset_path}?token={raw}"
        notify(db, Evento.RECUPERACION_CONTRASENA, [user],
               {"enlace_recuperacion": enlace, "horas_validez": s.reset_token_hours})
        audit.log(db, user, audit.Accion.RECUPERACION_SOLICITADA, "usuario", user.id, request=request)
        db.commit()
    return MessageResponse(detail="Si el correo está registrado, le enviamos un enlace para restablecer la contraseña.")


@router.post("/reset-password", response_model=MessageResponse, dependencies=[Depends(login_rate_limit)])
def reset_password(body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    user = find_user_by_reset_token(db, body.token)
    validate_password_strength(body.password)
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    user.reset_token_hash = None
    user.reset_expires_at = None
    reset_failed_logins(user)
    revoke_all_user_tokens(db, user.id)  # cierra todas las sesiones abiertas
    audit.log(db, user, audit.Accion.CONTRASENA_RESTABLECIDA, "usuario", user.id, request=request)
    db.commit()
    return MessageResponse(detail="Su contraseña fue restablecida. Inicie sesión con la nueva contraseña.")


@router.post("/change-password", response_model=MessageResponse)
def change_password(body: ChangePasswordRequest, request: Request, user: Usuario = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.password_actual, user.password_hash):
        raise AppError("La contraseña actual no es correcta.", "CONTRASENA_ACTUAL_INCORRECTA", status_code=400)
    validate_password_strength(body.password_nueva)
    user.password_hash = hash_password(body.password_nueva)
    user.password_changed_at = utcnow()
    revoke_all_user_tokens(db, user.id)
    audit.log(db, user, audit.Accion.CONTRASENA_RESTABLECIDA, "usuario", user.id, {"via": "cambio"}, request=request)
    db.commit()
    return MessageResponse(detail="Su contraseña fue actualizada. Vuelva a iniciar sesión.")


# ----------------------------------------------------------------------------- /me y preferencias
@router.get("/me", response_model=Me)
def me(user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_me(db, user)


@router.patch("/me/preferencias", response_model=Me)
def update_preferencias(body: PreferenciasUIUpdate, user: Usuario = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """PATCH parcial de las preferencias sensoriales. Devuelve el `Me` completo con `preferencias_ui` al día."""
    pref = db.scalar(select(PreferenciaSensorialUI).where(PreferenciaSensorialUI.usuario_id == user.id))
    if pref is None:
        pref = PreferenciaSensorialUI(usuario_id=user.id)
        db.add(pref)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        if valor is not None:
            setattr(pref, campo, valor)
    db.commit()
    db.refresh(pref)
    return build_me(db, user)


# ----------------------------------------------------------------------------- SSO OIDC
@router.get("/sso/login")
def sso_login():
    """Redirige al proveedor OIDC. 501 `SSO_NO_CONFIGURADO` si no está configurado."""
    return RedirectResponse(sso.build_login_url(), status_code=302)


@router.get("/sso/callback")
def sso_callback(request: Request, db: Session = Depends(get_db), code: str | None = None, state: str | None = None,
                 error: str | None = None):
    sso.ensure_configured()
    s = get_settings()
    login_url = f"{s.frontend_url.rstrip('/')}/login"
    if error or not code:
        return RedirectResponse(f"{login_url}?sso=error", status_code=302)
    sso.verify_state(state)
    ident = sso.exchange_code_for_identity(code)
    user = db.scalar(select(Usuario).where(Usuario.sso_subject == ident["sub"])) or db.scalar(
        select(Usuario).where(Usuario.email == ident["email"])
    )
    if user is None or not ident["email_verified"]:
        audit.log(db, None, audit.Accion.LOGIN_FALLIDO, "usuario", None, {"motivo": "sso_sin_cuenta"}, request=request,
                  commit=True)
        return RedirectResponse(f"{login_url}?sso=sin_cuenta", status_code=302)
    if str(user.estado) in (EstadoUsuario.INACTIVO, EstadoUsuario.SUSPENDIDO, EstadoUsuario.PENDIENTE_ACTIVACION):
        return RedirectResponse(f"{login_url}?sso=inactiva", status_code=302)
    if user.sso_subject is None:
        user.sso_subject = ident["sub"]
    user.fecha_ultima_sesion = utcnow()
    redirect = RedirectResponse(f"{login_url}?sso=ok", status_code=302)
    raw, _ = issue_refresh_token(db, user, ip=audit.client_ip(request), user_agent=request.headers.get("user-agent"))
    set_refresh_cookie(redirect, raw)
    audit.log(db, user, audit.Accion.LOGIN_OK, "usuario", user.id, {"via": "sso"}, request=request)
    db.commit()
    return redirect
