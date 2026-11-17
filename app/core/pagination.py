"""Paginación estándar: ``?page=&page_size=`` -> ``{items, total, page, page_size}``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageParams:
    """Dependencia: ``params: PageParams = Depends()``."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Número de página (desde 1)"),
        page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="Registros por página (máx. 100)"),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate(
    db: Session,
    stmt: Select,
    params: PageParams,
    transform: Callable[[Any], Any] | None = None,
    *,
    scalars: bool = True,
) -> dict:
    """Ejecuta `stmt` con LIMIT/OFFSET y cuenta el total. `transform` convierte cada fila (p. ej. a un schema)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    paged = stmt.limit(params.page_size).offset(params.offset)
    rows: Sequence[Any] = db.scalars(paged).all() if scalars else db.execute(paged).all()
    items = [transform(r) for r in rows] if transform else list(rows)
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
