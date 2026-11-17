"""Schemas comunes: errores, paginación y utilidades de serialización."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from app.core.pagination import Page  # noqa: F401  (re-export: Page[T] = {items,total,page,page_size})

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base para schemas de salida construidos desde objetos SQLAlchemy (`from_attributes`)."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ErrorResponse(BaseModel):
    detail: str
    code: str


class ValidationProblem(BaseModel):
    campo: str
    mensaje: str


class ValidationErrorResponse(ErrorResponse):
    errores: list[ValidationProblem] = []


class MessageResponse(BaseModel):
    detail: str


class IdResponse(BaseModel):
    id: int


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
