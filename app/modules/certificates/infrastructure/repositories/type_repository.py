"""SQL repository of certificate types."""

from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.infrastructure.orm.certificate_type import (
    CertificateTypeRow as Row,
)

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def to_entity(row: Row) -> CertificateType:
    """Map a row to the domain type."""
    return CertificateType(
        id=row.id,
        code=row.code,
        name={str(k): str(v) for k, v in row.name.items()},
        levels=[str(level) for level in row.levels],
        asks_level=row.asks_level,
        asks_score=row.asks_score,
        score_min=row.score_min,
        score_max=row.score_max,
        asks_percent=row.asks_percent,
        asks_subject=row.asks_subject,
        asks_year=row.asks_year,
        builtin=row.builtin,
        position=row.position,
    )


def _apply(row: Row, kind: CertificateType) -> None:
    row.code = kind.code
    row.name = dict(kind.name)
    row.levels = list(kind.levels)
    row.asks_level = kind.asks_level
    row.asks_score = kind.asks_score
    row.score_min = kind.score_min
    row.score_max = kind.score_max
    row.asks_percent = kind.asks_percent
    row.asks_subject = kind.asks_subject
    row.asks_year = kind.asks_year
    row.builtin = kind.builtin
    row.position = kind.position


class SqlCertificateTypeRepository:
    """Types in `certificates.types`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def list_all(self) -> list[CertificateType]:
        """Return all types by position."""
        stmt = select(Row).order_by(Row.position, Row.code)
        return [to_entity(row) for row in await self.session.scalars(stmt)]

    async def get(self, type_id: UUID) -> CertificateType | None:
        """Return the type or None."""
        row = await self.session.get(Row, type_id)
        return None if row is None else to_entity(row)

    async def get_by_code(self, code: str) -> CertificateType | None:
        """Return the type with this code or None."""
        row = await self.session.scalar(select(Row).where(Row.code == code))
        return None if row is None else to_entity(row)

    async def add(self, kind: CertificateType) -> None:
        """Insert a type."""
        row = Row(id=kind.id)
        _apply(row, kind)
        self.session.add(row)
        await self.session.flush()

    async def save(self, kind: CertificateType) -> None:
        """Write the type's fields."""
        row = await self.session.get(Row, kind.id)
        if row is not None:
            _apply(row, kind)
            await self.session.flush()

    async def delete(self, type_id: UUID) -> None:
        """Delete the type."""
        await self.session.execute(delete(Row).where(Row.id == type_id))

    async def next_position(self) -> int:
        """Return the position after the last type."""
        top = await self.session.scalar(select(func.max(Row.position)))
        return 0 if top is None else int(top) + 1
