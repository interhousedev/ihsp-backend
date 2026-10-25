"""Inserting a link with a fresh random slug, retrying on collisions (SL-2)."""

import random
from collections.abc import Callable

from app.modules.links.domain.errors import SlugsExhaustedError, SlugTakenError
from app.modules.links.domain.link import Link, LinkKind
from app.modules.links.domain.short_id import is_valid, new_slug
from app.modules.links.ports.unit_of_work import LinksUnitOfWork

MAX_FAILURES = 60


class SlugAllocator:
    """Finds a free slug; the ID grows by one character per 5 collisions."""

    def __init__(self, rng: random.Random) -> None:
        """Store the injected random source."""
        self.rng = rng

    async def add(
        self,
        uow: LinksUnitOfWork,
        build: Callable[[str], Link],
        *,
        kind: LinkKind,
        is_admin: bool = False,
        requested_length: int | None = None,
    ) -> Link:
        """Build the link with a candidate slug and insert it, retrying on clashes."""
        failures = 0
        while failures < MAX_FAILURES:
            slug = new_slug(
                kind,
                self.rng,
                failures=failures,
                requested_length=requested_length,
                is_admin=is_admin,
            )
            if kind in (LinkKind.URL, LinkKind.FILE) and not is_valid(slug):
                failures += 1
                continue
            link = build(slug)
            try:
                await uow.links.add(link)
            except SlugTakenError:
                failures += 1
                continue
            return link
        raise SlugsExhaustedError(support_details=f"no free slug for {kind}")
