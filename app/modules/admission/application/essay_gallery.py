"""The essay gallery: publish a version to other students, browse, fork a target.

Nothing in the gallery carries a name. Publishing needs the sharing consent and
freezes a version; authors who later withdraw the consent vanish from the list.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    EssayTooShortError,
    ItemLimitError,
)
from app.modules.admission.domain.essay_flow import (
    GalleryEntry,
    PromptTarget,
    prompt_key,
)
from app.modules.admission.domain.essays import (
    MAX_ESSAYS,
    Essay,
    EssayVersion,
    word_count,
)
from app.modules.admission.ports.consent import SHARING
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id

BROWSE_LIMIT: Final = 30
_FETCH: Final = 120
GALLERY_VERSION_NAME: Final = "Gallery"
MIN_WORDS: Final = 1


@dataclass(frozen=True, slots=True)
class GalleryItem:
    """A published essay version as other students see it: no author."""

    essay_id: UUID
    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    targets: tuple[PromptTarget, ...]
    version: int
    body: str
    word_count: int
    published_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class GalleryView:
    """The gallery of one student: what others published and what they published."""

    items: list[GalleryItem]
    mine: list[GalleryItem]


class EssayGalleryService:
    """Publish, unpublish, browse and fork."""

    def __init__(self, uow_factory: UowFactory, gate: FlowGate, clock: Clock) -> None:
        """Keep the transaction factory, the flow gate and the clock."""
        self._uow = uow_factory
        self._gate = gate
        self._clock = clock

    @staticmethod
    async def _own(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, essay_id: UUID
    ) -> Essay:
        essay = await uow.essays.get(essay_id)
        if essay is None or essay.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return essay

    async def publish(self, ctx: AdmissionContext, essay_id: UUID) -> GalleryItem:
        """Publish the essay's current text as a new version; sharing is required."""
        await self._gate.require(ctx, SHARING)
        now = self._clock.now()
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            count = word_count(essay.body)
            if count < MIN_WORDS:
                raise EssayTooShortError(params={"min": MIN_WORDS, "count": count})
            saved = await uow.essays.update(
                replace(
                    essay,
                    current_version=essay.current_version + 1,
                    last_snapshot_at=now,
                    updated_at=now,
                )
            )
            version = await uow.essays.add_version(
                EssayVersion(
                    id=new_id(),
                    essay_id=saved.id,
                    version=saved.current_version,
                    body=saved.body,
                    created_by=ctx.user_id,
                    source="explicit",
                    name=GALLERY_VERSION_NAME,
                    word_count=count,
                    created_at=now,
                )
            )
            entry = await uow.gallery.publish(
                GalleryEntry(
                    new_id(), saved.id, ctx.user_id, version.version, published_at=now
                )
            )
            await uow.commit()
            return _item(saved, entry, version.body)

    async def unpublish(self, ctx: AdmissionContext, essay_id: UUID) -> None:
        """Take the essay out of the gallery; withdrawing needs no consent."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            await self._own(uow, ctx, essay_id)
            await uow.gallery.unpublish(essay_id)
            await uow.commit()

    async def browse(
        self, ctx: AdmissionContext, limit: int = BROWSE_LIMIT
    ) -> GalleryView:
        """Others' published essays (authors who consented) and the student's own."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            mine = await self._items(uow, await uow.gallery.by_student(ctx.user_id))
            entries = await uow.gallery.others(ctx.user_id, _FETCH)
            allowed = await self._gate.sharing(sorted({e.student_id for e in entries}))
            shown = [e for e in entries if e.student_id in allowed][:limit]
            return GalleryView(await self._items(uow, shown), mine)

    @staticmethod
    async def _items(
        uow: AdmissionUnitOfWork, entries: Sequence[GalleryEntry]
    ) -> list[GalleryItem]:
        out: list[GalleryItem] = []
        for entry in entries:
            essay = await uow.essays.get(entry.essay_id)
            version = await uow.essays.version(entry.essay_id, entry.version)
            if essay is not None and version is not None:
                out.append(_item(essay, entry, version.body))
        return out

    async def fork(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        institution_id: UUID | None,
        position: int,
    ) -> tuple[Essay, Essay]:
        """Copy the body into a new essay for one target; the parent loses it.

        Returns (parent, fork).
        """
        await self._gate.owner(ctx)
        key = prompt_key(institution_id, position)
        now = self._clock.now()
        async with self._uow() as uow:
            parent = await self._own(uow, ctx, essay_id)
            target = next((t for t in parent.targets if t.key == key), None)
            if target is None:
                raise AdmissionNotFoundError()
            if len(await uow.essays.list_for(ctx.user_id)) >= MAX_ESSAYS:
                raise ItemLimitError(params={"kind": "essay", "limit": MAX_ESSAYS})
            child = await uow.essays.add(
                Essay(
                    id=new_id(),
                    student_id=ctx.user_id,
                    kind=parent.kind,
                    title=parent.title,
                    prompt_text=target.prompt,
                    word_limit=target.word_limit,
                    body=parent.body,
                    targets=(target,),
                    forked_from=parent.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            rest = tuple(t for t in parent.targets if t.key != key)
            saved = await uow.essays.update(
                replace(parent, targets=rest, updated_at=now)
            )
            await uow.commit()
            return saved, child


def _item(essay: Essay, entry: GalleryEntry, body: str) -> GalleryItem:
    return GalleryItem(
        essay_id=essay.id,
        kind=essay.kind,
        title=essay.title,
        prompt_text=essay.prompt_text,
        word_limit=essay.word_limit,
        targets=essay.targets,
        version=entry.version,
        body=body,
        word_count=word_count(body),
        published_at=entry.published_at,
    )
