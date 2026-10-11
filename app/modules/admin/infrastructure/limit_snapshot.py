"""Reads the runtime limits in one session: what `EffectiveLimits` caches."""

from app.modules.admin.domain.limits import (
    LimitInvalidError,
    check_value,
    overrides_from_rows,
    spec_of,
)
from app.modules.admin.infrastructure.repositories.limit_store import SqlLimitStore
from app.shared.limits import LimitExtension, LimitSnapshot

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def load_limit_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> LimitSnapshot:
    """The valid overrides and the extensions; invalid stored values are left out."""
    async with sessionmaker() as session:
        store = SqlLimitStore(session)
        overrides = overrides_from_rows(await store.read_overrides())
        extensions = {
            record.user_id: LimitExtension(
                multiplier=record.terms.multiplier,
                values=_valid_values(record.terms.values),
                expires_on=record.terms.expires_on,
            )
            for record in await store.read_extensions()
        }
    return LimitSnapshot(overrides=overrides, extensions=extensions)


def _valid_values(values: dict[str, int]) -> dict[str, int]:
    valid: dict[str, int] = {}
    for key, value in values.items():
        try:
            checked = check_value(spec_of(key), value)
        except LimitInvalidError:
            continue
        if checked is not None:
            valid[key] = checked
    return valid
