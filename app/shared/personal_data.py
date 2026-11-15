"""Personal data of one user: what a module exports and what it erases.

Every module that stores rows about a user describes its tables once, as a list of
``PersonalTable`` items (``<module>/infrastructure/personal_data.py``). The privacy
module reads the descriptions for the data export and runs ``erase`` at the end of
an approved account deletion. A table is always one of four treatments:

- ``ERASE``: the rows are deleted.
- ``NULLIFY``: the rows stay (statistics), the user reference is set to NULL.
- ``RETAIN``: school or audit records the lyceum keeps; the user row is anonymised,
  so the kept rows no longer identify anyone outside the school's own records.
- ``ANONYMISE``: the row is rewritten by the owning module (``id.users``).
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import ARRAY, Float, LargeBinary, delete, inspect, select, update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

EXPORT_ROW_LIMIT = 20_000
_SKIPPED_TYPES = (LargeBinary, TSVECTOR)


class Treatment(enum.StrEnum):
    """What happens to the rows of a table when the user is erased."""

    ERASE = "erase"
    NULLIFY = "nullify"
    RETAIN = "retain"
    ANONYMISE = "anonymise"


class PersonalData(Protocol):
    """One module's personal data (export and erasure)."""

    def tables(self) -> Sequence["PersonalTable"]:
        """The described tables, children before parents."""
        ...

    async def export(self, user_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Rows about the user by table name, without secrets and binary data."""
        ...

    async def erase(self, user_id: UUID) -> int:
        """Delete or nullify the user's rows; return how many rows were touched."""
        ...


@dataclass(frozen=True, slots=True)
class ParentLink:
    """A child table without an owner column: rows hang off an owned parent."""

    parent: type[DeclarativeBase]
    child_fk: str  # attribute of the child that holds the parent id
    parent_owner: str  # attribute of the parent that holds the user id


@dataclass(frozen=True, slots=True)
class PersonalTable:
    """How one table relates to a user and what is done with it."""

    model: type[DeclarativeBase]
    treatment: Treatment
    owner: str | None = None  # attribute of the model that holds the user id
    parent: ParentLink | None = None
    exclude: tuple[str, ...] = ()  # attributes never exported (secrets)
    note: str = ""
    export: bool = True
    # RETAIN rows keep their data but these columns are set to NULL when erased.
    scrub: tuple[str, ...] = ()

    @property
    def erased_elsewhere(self) -> bool:
        """True when another task (``<module>.delete_owner``) erases the table."""
        return self.note.startswith("erased by ")

    @property
    def name(self) -> str:
        """``schema.table``."""
        table: Any = self.model.__table__
        return f"{table.schema}.{table.name}"

    def matches(self, user_id: UUID) -> Any:
        """SQL condition that selects the user's rows."""
        if self.parent is not None:
            link = self.parent
            owned = select(link.parent.id).where(  # type: ignore[attr-defined]
                getattr(link.parent, link.parent_owner) == user_id
            )
            return getattr(self.model, link.child_fk).in_(owned)
        if self.owner is None:
            raise ValueError(f"{self.name} needs an owner or a parent link")
        return getattr(self.model, self.owner) == user_id


def to_json_value(value: Any) -> Any:
    """Make a column value JSON-safe (UUID, datetimes, decimals, enums, bytes)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return to_json_value(value.value)
    if isinstance(value, Mapping):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json_value(v) for v in value]
    if isinstance(value, bytes | bytearray | memoryview):
        return None
    return str(value)


def exported_columns(spec: PersonalTable) -> list[str]:
    """Attribute names of the columns that may be exported."""
    keys: list[str] = []
    for attr in inspect(spec.model).column_attrs:
        column = attr.columns[0]
        if attr.key in spec.exclude or isinstance(column.type, _SKIPPED_TYPES):
            continue
        if isinstance(column.type, ARRAY) and isinstance(column.type.item_type, Float):
            continue  # embeddings
        if type(column.type).__name__ in {"Vector", "HALFVEC", "VECTOR"}:
            continue
        keys.append(attr.key)
    return keys


@dataclass(slots=True)
class SqlPersonalData:
    """``PersonalData`` over SQLAlchemy models; one transaction per call."""

    sessionmaker: async_sessionmaker[AsyncSession]
    specs: Sequence[PersonalTable] = field(default_factory=tuple)

    def tables(self) -> Sequence[PersonalTable]:
        """The described tables."""
        return self.specs

    async def export(self, user_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Select the user's rows of every exportable table."""
        out: dict[str, list[dict[str, Any]]] = {}
        async with self.sessionmaker() as session:
            for spec in self.specs:
                if not spec.export:
                    continue
                keys = exported_columns(spec)
                columns = [getattr(spec.model, key) for key in keys]
                stmt = select(*columns).where(spec.matches(user_id))
                result = await session.execute(stmt.limit(EXPORT_ROW_LIMIT))
                out[spec.name] = [
                    {k: to_json_value(v) for k, v in zip(keys, row, strict=True)}
                    for row in result.all()
                ]
        return out

    async def erase(self, user_id: UUID) -> int:
        """Delete the ERASE tables and clear the NULLIFY columns, atomically."""
        touched = 0
        async with self.sessionmaker() as session, session.begin():
            for spec in self.specs:
                if spec.treatment is Treatment.ERASE:
                    result = await session.execute(
                        delete(spec.model).where(spec.matches(user_id))
                    )
                elif spec.treatment is Treatment.NULLIFY and spec.owner is not None:
                    result = await session.execute(
                        update(spec.model)
                        .where(spec.matches(user_id))
                        .values({spec.owner: None})
                    )
                elif spec.treatment is Treatment.RETAIN and spec.scrub:
                    result = await session.execute(
                        update(spec.model)
                        .where(spec.matches(user_id))
                        .values(dict.fromkeys(spec.scrub))
                    )
                else:
                    continue
                touched += int(getattr(result, "rowcount", 0) or 0)
        return touched
