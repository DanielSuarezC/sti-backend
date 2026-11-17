"""Base declarativa, tipos portables SQLite/PostgreSQL, mixins y salvaguardas ORM.

* `JSON_T`       JSON portable (JSONB solo como variante en PostgreSQL).
* `UTCDateTime`  DateTime con zona horaria siempre en UTC (SQLite pierde el tzinfo).
* Mixins         `IdMixin`, `TimestampMixin`, `SoftDeleteMixin` (RF-37).
* Salvaguardas   filtro automatico de soft-deleted y bloqueo de DELETE fisico.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    with_loader_criteria,
)
from sqlalchemy.types import TypeDecorator

from app.core.crypto import EncryptedDate, EncryptedJSON, EncryptedText

# ---------------------------------------------------------------- tipos portables
JSON_T = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """DateTime(timezone=True) que siempre entrega valores *aware* en UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


# Alias de anotacion -> tipo SQL (se usan como `Mapped[S100]`, `Mapped[TXT | None]`...)
S20 = Annotated[str, 20]
S30 = Annotated[str, 30]
S50 = Annotated[str, 50]
S100 = Annotated[str, 100]
S200 = Annotated[str, 200]
S255 = Annotated[str, 255]
S500 = Annotated[str, 500]
S1000 = Annotated[str, 1000]
TXT = Annotated[str, "text"]
CTXT = Annotated[str, "ctext"]  # texto cifrado AES-256-GCM
CJSON = Annotated[dict, "cjson"]  # JSON cifrado
CDATE = Annotated[date, "cdate"]  # fecha cifrada
JS = Annotated[dict, "json"]  # JSON/JSONB
JSL = Annotated[list, "jsonlist"]  # lista JSON/JSONB
DEC = Annotated[Decimal, "dec"]
DT = Annotated[datetime, "dt"]


class Base(DeclarativeBase):
    type_annotation_map = {
        S20: String(20),
        S30: String(30),
        S50: String(50),
        S100: String(100),
        S200: String(200),
        S255: String(255),
        S500: String(500),
        S1000: String(1000),
        TXT: Text(),
        CTXT: EncryptedText(),
        CJSON: EncryptedJSON(),
        CDATE: EncryptedDate(),
        JS: JSON_T,
        JSL: JSON_T,
        DEC: Numeric(10, 2),
        DT: UTCDateTime(),
        str: String(255),
        bool: Boolean(),
        int: Integer(),
        date: Date(),
        datetime: UTCDateTime(),
        time: Time(),
    }


# ---------------------------------------------------------------- columnas auxiliares
def fk(
    target: str,
    *,
    nullable: bool = False,
    index: bool = True,
    ondelete: str | None = None,
    unique: bool = False,
):
    """Clave foranea `Integer` hacia ``tabla.id``."""
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index, unique=unique)


def enum_col(enum_cls: type[enum.Enum], *, default: Any = None, nullable: bool = False, length: int = 40):
    """Columna Enum NO nativa (VARCHAR + CHECK portable). El nombre del CHECK se asigna al final."""
    return mapped_column(
        Enum(
            enum_cls,
            native_enum=False,
            create_constraint=True,
            length=length,
            validate_strings=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=nullable,
        default=default,
    )


def unique_active(name: str, *columns: str) -> Index:
    """Indice UNICO parcial (solo filas no eliminadas): compatible con SQLite y PostgreSQL."""
    where = text("deleted_at IS NULL")
    return Index(name, *columns, unique=True, sqlite_where=where, postgresql_where=where)


# ---------------------------------------------------------------- mixins
class IdMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    """Soft delete universal (RF-37). Las consultas ORM excluyen `deleted_at IS NOT NULL` por defecto.

    Para ver tambien los eliminados: ``select(...).execution_options(include_deleted=True)``.
    ``deleted_by_id`` no lleva FK a proposito (evita ciclos y bloqueos al archivar usuarios).
    """

    __allow_hard_delete__ = False  # catalogos (ESTADO_PLAN) lo ponen en True

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    deleted_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, actor_id: int | None = None, reason: str | None = None) -> None:
        self.deleted_at = utcnow()
        self.deleted_by_id = actor_id
        self.deleted_reason = reason

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by_id = None
        self.deleted_reason = None


class Entity(IdMixin, TimestampMixin, SoftDeleteMixin):
    """Mixin estandar de toda entidad de negocio: id + timestamps + soft delete."""


class HardDeleteForbidden(RuntimeError):
    """Se intento un DELETE fisico sobre una entidad con soft delete."""


# ---------------------------------------------------------------- salvaguardas ORM
@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state):
    if (
        state.is_select
        and not state.is_column_load
        and not state.execution_options.get("include_deleted", False)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(SoftDeleteMixin, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
        )


@event.listens_for(Session, "before_flush")
def _forbid_hard_delete(session, flush_context, instances):
    if session.info.get("allow_hard_delete"):
        return
    for obj in session.deleted:
        if isinstance(obj, SoftDeleteMixin) and not getattr(obj, "__allow_hard_delete__", False):
            raise HardDeleteForbidden(
                f"No se permite eliminar fisicamente {type(obj).__name__}: use soft_delete() (RF-37)."
            )


def finalize_check_constraint_names(metadata) -> None:
    """Nombra de forma unica los CHECK de los Enum no nativos: `ck_<tabla>_<columna>` (max. 63 caracteres).

    Sin esto, dos columnas de una misma tabla con el mismo Enum (p. ej. NivelBMA) generarian CHECK homonimos,
    lo cual PostgreSQL rechaza. Tambien fija `Enum.name` para que Alembic renderice el mismo nombre.
    """
    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Enum) and not col.type.native_enum:
                col.type.name = f"ck_{table.name}_{col.name}"[:63]
        for c in list(table.constraints):
            if isinstance(c, CheckConstraint) and getattr(c, "_type_bound", False):
                cols = list(c.columns)
                if len(cols) == 1:
                    c.name = f"ck_{table.name}_{cols[0].name}"[:63]
