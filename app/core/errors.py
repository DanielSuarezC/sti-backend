"""Errores de la API: formato uniforme `{"detail": "...", "code": "SNAKE_CASE"}` en español claro.

Uso:  ``raise Forbidden("No tiene permiso para ver este dato.", "SIN_PERMISO")``
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("sti.errors")

_DEFAULTS = {
    400: ("La solicitud no es válida. Revise los datos enviados.", "SOLICITUD_INVALIDA"),
    401: ("Debe iniciar sesión para continuar.", "NO_AUTENTICADO"),
    403: ("No tiene permiso para realizar esta acción.", "ACCESO_DENEGADO"),
    404: ("No encontramos lo que busca.", "NO_ENCONTRADO"),
    405: ("Este método no está permitido para esta dirección.", "METODO_NO_PERMITIDO"),
    409: ("La operación genera un conflicto con el estado actual.", "CONFLICTO"),
    413: ("El archivo es demasiado grande.", "ARCHIVO_MUY_GRANDE"),
    422: ("Algunos datos no son válidos. Revíselos e intente de nuevo.", "DATOS_INVALIDOS"),
    423: ("La cuenta está bloqueada temporalmente.", "CUENTA_BLOQUEADA"),
    429: ("Demasiadas solicitudes. Espere un momento e intente de nuevo.", "DEMASIADAS_SOLICITUDES"),
    500: ("Ocurrió un error inesperado. Ya fue registrado; intente de nuevo más tarde.", "ERROR_INTERNO"),
    501: ("Esta función no está configurada en este momento.", "NO_IMPLEMENTADO"),
    503: ("El servicio no está disponible en este momento.", "SERVICIO_NO_DISPONIBLE"),
}


class AppError(Exception):
    """Error de negocio/HTTP con `detail` (español) y `code` estable para el frontend."""

    status_code = 400
    default_code = "SOLICITUD_INVALIDA"
    default_detail = "La solicitud no es válida."

    def __init__(self, detail: str | None = None, code: str | None = None, *, headers: dict | None = None,
                 extra: dict | None = None, status_code: int | None = None):
        self.detail = detail or self.default_detail
        self.code = code or self.default_code
        self.headers = headers
        self.extra = extra
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class BadRequest(AppError):
    status_code = 400


class Unauthorized(AppError):
    status_code = 401
    default_code = "NO_AUTENTICADO"
    default_detail = "Debe iniciar sesión para continuar."


class Forbidden(AppError):
    status_code = 403
    default_code = "ACCESO_DENEGADO"
    default_detail = "No tiene permiso para realizar esta acción."


class NotFound(AppError):
    status_code = 404
    default_code = "NO_ENCONTRADO"
    default_detail = "No encontramos lo que busca."


class Conflict(AppError):
    status_code = 409
    default_code = "CONFLICTO"
    default_detail = "La operación genera un conflicto con el estado actual."


class Unprocessable(AppError):
    status_code = 422
    default_code = "DATOS_INVALIDOS"
    default_detail = "Algunos datos no son válidos."


class Locked(AppError):
    status_code = 423
    default_code = "CUENTA_BLOQUEADA"


class TooManyRequests(AppError):
    status_code = 429
    default_code = "DEMASIADAS_SOLICITUDES"


class NotImplementedFeature(AppError):
    status_code = 501
    default_code = "NO_IMPLEMENTADO"


class ConsentRequired(Forbidden):
    default_code = "CONSENTIMIENTO_REQUERIDO"
    default_detail = (
        "Debe firmar el consentimiento informado (F0) antes de continuar. "
        "Ingrese a la sección de consentimiento y complete la firma."
    )


def error_body(detail: str, code: str, extra: dict | None = None) -> dict:
    body = {"detail": detail, "code": code}
    if extra:
        body.update(extra)
    return body


def _field_label(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or "solicitud"


_PYDANTIC_ES = {
    "missing": "es obligatorio",
    "string_too_short": "es demasiado corto",
    "string_too_long": "es demasiado largo",
    "value_error": "no es válido",
    "int_parsing": "debe ser un número entero",
    "float_parsing": "debe ser un número",
    "bool_parsing": "debe ser verdadero o falso",
    "enum": "no es una opción permitida",
    "literal_error": "no es una opción permitida",
    "greater_than_equal": "es menor que el mínimo permitido",
    "less_than_equal": "supera el máximo permitido",
    "date_parsing": "debe ser una fecha válida (AAAA-MM-DD)",
    "datetime_parsing": "debe ser una fecha y hora válidas",
    "json_invalid": "el cuerpo no es un JSON válido",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.detail, exc.code, exc.extra), status_code=exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        default_detail, default_code = _DEFAULTS.get(exc.status_code, ("Error en la solicitud.", "ERROR"))
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code not in (404, 405) else default_detail
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            body = exc.detail
            return JSONResponse(
                error_body(str(body.get("detail", default_detail)), str(body.get("code", default_code))),
                status_code=exc.status_code, headers=getattr(exc, "headers", None))
        return JSONResponse(error_body(detail, default_code), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            label = _field_label(tuple(err.get("loc", ())))
            msg = _PYDANTIC_ES.get(err.get("type", ""), None)
            if msg is None:
                msg = "no es válido"
                if err.get("type", "").startswith("value_error") and err.get("msg"):
                    msg = str(err["msg"]).removeprefix("Value error, ")
            problems.append({"campo": label, "mensaje": f"{label} {msg}" if not msg[0].isupper() else msg})
        resumen = "; ".join(p["mensaje"] for p in problems[:3])
        detail = f"Revise los datos enviados: {resumen}." if resumen else _DEFAULTS[422][0]
        return JSONResponse(error_body(detail, "DATOS_INVALIDOS", {"errores": problems}), status_code=422)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError):
        logger.warning("IntegrityError: %s", exc.orig)
        return JSONResponse(
            error_body("Ya existe un registro con esos datos o falta una relación obligatoria. Revise e intente de nuevo.",
                       "CONFLICTO_INTEGRIDAD"),
            status_code=409,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover
            pass
        return JSONResponse(error_body(*_DEFAULTS[500]), status_code=500)
