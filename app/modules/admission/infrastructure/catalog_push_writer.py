"""Pushed institutions written with the seed loader, one savepoint per item."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.catalog_push import PushResult, PushStatus
from app.modules.admission.domain.errors import MediaUnreachableError
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.infrastructure.catalog_data import Institution
from app.modules.admission.infrastructure.catalog_loader import _Loader, seed_id
from app.modules.admission.infrastructure.org_media import (
    OrgMedia,
    by_domain,
    load_org_media,
    normalize_domain,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow, SourceRow
from app.modules.admission.ports.media_mirror import MediaMirror
from app.shared.clock import Clock

import structlog
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MEDIA = ("logo_url", "cover_url")
log = structlog.get_logger(__name__)
_VOLATILE = frozenset({"checked_at"})
"""Columns the loader stamps on every write; a new stamp alone is no change."""


def _changed(session: AsyncSession) -> bool:
    if session.new:
        return True
    for obj in session.dirty:
        for attr in inspect(obj).attrs:
            if attr.key not in _VOLATILE and attr.history.has_changes():
                return True
    return False


def _invalid_field(error: ValidationError) -> str:
    loc = error.errors()[0].get("loc") or ("item",)
    return ".".join(str(p) for p in loc)


def _validated(index: int, raw: dict[str, Any]) -> dict[str, Any] | PushResult:
    """The item in the seed shape, or its `invalid` result."""
    key = str(raw.get("slug") or raw.get("website_domain") or index)
    try:
        d = Institution.model_validate(
            {k: v for k, v in raw.items() if k not in _MEDIA}
        ).model_dump(mode="json")
    except ValidationError as e:
        return PushResult(index, key, "invalid", _invalid_field(e))
    for name in _MEDIA:
        value = raw.get(name)
        if value is not None and not (isinstance(value, str) and is_https_url(value)):
            return PushResult(index, d["slug"], "invalid", name)
    return d


async def _write(
    session: AsyncSession, loader: _Loader, d: dict[str, Any], owner: UUID | None
) -> bool | None:
    """Write one item in a savepoint: whether anything changed, None on failure."""
    nested = await session.begin_nested()
    changed: bool | None
    try:
        with session.no_autoflush:
            await loader.institution(d, owner)
            changed = _changed(session)
        if changed:
            # Facts point at sources without an ORM relationship, so the unit of
            # work cannot order them: write the new sources first.
            await session.flush([o for o in session.new if isinstance(o, SourceRow)])
            await session.flush()
            await nested.commit()
    except (SQLAlchemyError, KeyError, TypeError, ValueError):
        log.warning("catalog_push_item_failed", slug=d.get("slug"), exc_info=True)
        changed = None
    if not changed:
        # Nothing to write, or the item failed: drop its savepoint (and the
        # sources it would have added) so the next item starts clean.
        await nested.rollback()
        loader.sources.clear()
    return changed


class SqlInstitutionPushWriter:
    """Validates the seed shape and upserts by slug, mirroring logo and cover.

    A row that already has a mirrored image keeps it; an image that cannot be
    fetched is left out with a warning instead of failing the item.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        mirror: MediaMirror | None,
    ) -> None:
        """Keep the sessionmaker, the clock and the image mirror."""
        self._sm = sessionmaker
        self._clock = clock
        self._mirror = mirror
        self._media: dict[str, OrgMedia] | None = None

    async def upsert(self, items: list[dict[str, Any]]) -> list[PushResult]:
        """One result per item, in order; a bad item never stops the others."""
        if self._media is None:
            self._media = by_domain(load_org_media())
        results: list[PushResult] = []
        async with self._sm.begin() as session:
            loader = _Loader(session, self._clock.now(), {}, None)
            for index, raw in enumerate(items):
                results.append(await self._one(session, loader, index, raw))
        return results

    async def _one(
        self, session: AsyncSession, loader: _Loader, index: int, raw: dict[str, Any]
    ) -> PushResult:
        checked = _validated(index, raw)
        if isinstance(checked, PushResult):
            return checked
        d, key = checked, checked["slug"]
        domain = normalize_domain(d.get("website_domain"))
        owner = await loader.owner_of_domain(domain) if domain is not None else None
        inst = seed_id("institution", key)
        if owner == inst:
            owner = None
        existing = await session.get(InstitutionRow, owner or inst)
        warnings: list[str] = []
        if owner is None:
            org = (self._media or {}).get(domain or "")
            for name in _MEDIA:
                source = raw.get(name) or (getattr(org, name) if org else None)
                d[name] = await self._image(
                    source, getattr(existing, name, None), name, warnings
                )
        changed = await _write(session, loader, d, owner)
        if changed is None:
            return PushResult(index, key, "invalid", "item")
        status: PushStatus = "unchanged"
        if changed:
            status = "created" if existing is None else "updated"
        return PushResult(index, key, status, warnings=tuple(warnings))

    async def _image(
        self, source: str | None, current: str | None, name: str, warnings: list[str]
    ) -> str | None:
        """The stored image URL: the mirrored source, else what the row has."""
        if not source:
            return current
        if not is_https_url(source):
            # An org-media fallback may be plain http; the row only takes https.
            warnings.append(name)
            return current
        if self._mirror is None:
            return current or source
        if current and current.startswith(self._mirror.own_prefix):
            return current
        try:
            mirrored = await self._mirror.mirror(source)
        except MediaUnreachableError:
            mirrored = None
        if mirrored is None or not is_https_url(mirrored):
            # Unreachable, or a local http storage the https-only column refuses.
            warnings.append(name)
            return current
        return mirrored
