"""Dependencias FastAPI reutilizables por todos los routers.

* ``get_db``                    sesión por petición.
* ``get_current_user``          usuario del Bearer JWT (ACTIVO o PENDIENTE_CONSENTIMIENTO).
* ``get_active_user``           igual, pero exige estado ACTIVO.
* ``require_roles(*roles)``     autorización por rol.
* ``require_consent``           bloquea estudiantes sin F0 firmado (403 ``CONSENTIMIENTO_REQUERIDO``).
* ``require_roles_consent(...)`` rol + consentimiento en una sola dependencia.
* helpers de alcance re-exportados desde ``permissions`` (``can_access_student``, ``assert_can``...).

Ejemplo::

    @router.get("/estudiantes/{estudiante_id}/aq10")
    def ver(estudiante_id: int, db: Session = Depends(get_db),
            user: Usuario = Depends(require_roles(Rol.BIENESTAR, Rol.ESTUDIANTE))):
        assert_can(db, user, estudiante_id, Recurso.AQ10, Accion.LEER)
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.audit import client_ip
from app.core.db import get_db
from app.core.errors import ConsentRequired, Forbidden, Unauthorized
from app.core.permissions import (  # noqa: F401  (re-export para los routers)
    Accion,
    Recurso,
    acciones_permitidas,
    assert_can,
    can,
    can_access_student,
    can_view_aq10,
    can_view_clinical,
    can_view_plan,
    can_write,
    coordinador_programa_ids,
    docente_ajuste_ids,
    get_estudiante_or_404,
    get_own_estudiante,
    student_has_consent,
    students_scope_criterion,
    students_scope_criterion_db,
    user_has_consent,
)
from app.core.security import decode_access_token
from app.models.enums import EstadoUsuario, Rol
from app.models.usuarios import Usuario

_bearer = HTTPBearer(auto_error=False)

__all__ = [
    "get_db", "get_current_user", "get_active_user", "require_roles", "require_consent", "require_roles_consent",
    "get_request_ip", "Accion", "Recurso", "acciones_permitidas", "assert_can", "can", "can_access_student",
    "can_view_aq10", "can_view_clinical", "can_view_plan", "can_write", "coordinador_programa_ids",
    "docente_ajuste_ids", "get_estudiante_or_404", "get_own_estudiante", "student_has_consent",
    "students_scope_criterion", "students_scope_criterion_db", "user_has_consent",
]


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    if creds is None or not creds.credentials:
        raise Unauthorized("Debe iniciar sesión para continuar.", "NO_AUTENTICADO", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(creds.credentials)
    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError):
        raise Unauthorized("Su sesión no es válida. Inicie sesión de nuevo.", "TOKEN_INVALIDO")
    user = db.get(Usuario, uid)
    if user is None:
        raise Unauthorized("Su sesión no es válida. Inicie sesión de nuevo.", "TOKEN_INVALIDO")
    if str(user.estado) not in (EstadoUsuario.ACTIVO, EstadoUsuario.PENDIENTE_CONSENTIMIENTO):
        raise Forbidden("Su cuenta no está activa. Comuníquese con el administrador.", "CUENTA_INACTIVA")
    request.state.user_id = user.id
    return user


def get_active_user(user: Usuario = Depends(get_current_user)) -> Usuario:
    if str(user.estado) != EstadoUsuario.ACTIVO:
        raise ConsentRequired()
    return user


def require_roles(*roles: Rol | str) -> Callable[..., Usuario]:
    """Permite solo los roles indicados (no exige consentimiento: úsela en endpoints de F0/cuenta)."""
    allowed = {str(r) for r in roles}

    def _dep(user: Usuario = Depends(get_current_user)) -> Usuario:
        if str(user.rol) not in allowed:
            raise Forbidden(
                "Su rol no tiene permiso para esta acción.", "ROL_NO_PERMITIDO",
                extra={"roles_permitidos": sorted(allowed)},
            )
        return user

    return _dep


def require_consent(user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    """Gate F0 (RF-05): el ESTUDIANTE sin consentimiento firmado recibe 403 ``CONSENTIMIENTO_REQUERIDO``."""
    if not user_has_consent(db, user):
        raise ConsentRequired()
    return user


def require_roles_consent(*roles: Rol | str) -> Callable[..., Usuario]:
    """Rol + gate de consentimiento (para todo endpoint de F1–F10 o datos propios del estudiante)."""
    allowed = {str(r) for r in roles}

    def _dep(user: Usuario = Depends(require_consent)) -> Usuario:
        if str(user.rol) not in allowed:
            raise Forbidden("Su rol no tiene permiso para esta acción.", "ROL_NO_PERMITIDO",
                            extra={"roles_permitidos": sorted(allowed)})
        return user

    return _dep


def get_request_ip(request: Request) -> str | None:
    return client_ip(request)
