"""Link an activity to an opportunity, or propose a new one ("not in the list").

A student types one short line (a link, or a name and an organization). The line
is untrusted: control and format characters and angle brackets are removed, only
one public `https` link is allowed, and the intake treats it as delimited data.
The researched draft is offered with the catalog entries and pending proposals it
resembles. Linking a new draft reuses a pending proposal with the same key, so the
moderators see one submission; approval points every linked activity at the
published entry, and reads join the current entry, so later edits reach them.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import OpportunityService
from app.modules.admission.application.opportunity_intake import (
    IntakeDraft,
    OpportunityIntake,
    extract_links,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.opportunities import (
    ItemOpportunityLink,
    Opportunity,
    OpportunityDraft,
    OpportunityMaterial,
    OpportunitySubmission,
)
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.opportunities import OpportunityRepository
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

QUERY_MAX: Final = 300
LOOKUP_PER_DAY: Final = 10
MAX_MATCHES: Final = 5
_DAY: Final = 86_400
_MIN_TITLE: Final = 4
_NOTE: Final = "Proposed by a student from an activity (not in the list)."
_WORD = re.compile(r"[^\w]+", re.UNICODE)

LinkStatus = Literal["pending", "verified", "rejected"]


def sanitize_query(text: str) -> str:
    """One clean line, or `ValidationFailedError(field=query)`.

    Control, format and private-use characters become spaces, angle brackets are
    dropped (no delimiter tags reach the prompt), whitespace collapses. At most
    one link, and it must be `https`.
    """
    if len(text) > QUERY_MAX:
        raise ValidationFailedError(params={"field": "query"})
    kept = "".join(
        " " if unicodedata.category(ch)[0] == "C" or ch in "<>" else ch
        for ch in unicodedata.normalize("NFKC", text)
    )
    clean = " ".join(kept.split())
    if not clean or len(clean) > QUERY_MAX:
        raise ValidationFailedError(params={"field": "query"})
    links = extract_links(clean)
    if len(links) > 1 or any(not u.lower().startswith("https://") for u in links):
        raise ValidationFailedError(params={"field": "query"})
    return clean


def _norm(text: str | None) -> str:
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(_WORD.sub(" ", folded).replace("_", " ").split())


def dedup_keys(title: str, provider: str | None, url: str | None) -> set[str]:
    """Keys under which two proposals count as the same opportunity.

    `url:<host><path>` (scheme, `www.`, query, fragment and trailing slash
    ignored) and `name:<title>|<provider>` (case, accents of width and
    punctuation ignored).
    """
    keys: set[str] = set()
    if url:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().removeprefix("www.")
        if host:
            keys.add(f"url:{host}{parts.path.rstrip('/').lower()}")
    name = _norm(title)
    if name:
        keys.add(f"name:{name}|{_norm(provider)}")
    return keys


def _keys_of(d: OpportunityDraft) -> set[str]:
    return dedup_keys(d.title, d.provider, d.url)


def _similar(d: OpportunityDraft, keys: set[str], title: str) -> bool:
    if keys & _keys_of(d):
        return True
    other = _norm(d.title)
    return (
        len(title) >= _MIN_TITLE
        and len(other) >= _MIN_TITLE
        and (title in other or other in title)
    )


def proposal_of(draft: IntakeDraft) -> OpportunityDraft:
    """The moderation draft of a researched (or student-edited) intake draft."""
    try:
        return OpportunityDraft(
            kind=draft.kind,  # type: ignore[arg-type]
            title=draft.title.strip(),
            summary=draft.summary.strip() or None,
            url=draft.url.strip() or None,
            provider=draft.provider.strip() or None,
            subject_ids=tuple(UUID(s) for s in draft.subject_ids),
            registration_deadlines=tuple(
                dt.date.fromisoformat(d) for d in draft.registration_deadlines
            ),
            exam_dates=tuple(dt.date.fromisoformat(d) for d in draft.event_dates),
            recurrence=draft.recurrence or None,
            materials=tuple(
                OpportunityMaterial(kind="link", title=m["title"], url=m["url"])
                for m in draft.materials
            ),
            note=_NOTE,
        )
    except (ValueError, KeyError, TypeError):
        raise ValidationFailedError(params={"field": "draft"})


@dataclass(frozen=True, slots=True)
class Lookup:
    """A researched draft with what already exists."""

    draft: IntakeDraft
    matches: list[Opportunity]
    pending: OpportunitySubmission | None


@dataclass(frozen=True, slots=True)
class ItemOpportunityView:
    """The opportunity of an activity with its current data."""

    item_id: UUID
    status: LinkStatus
    opportunity_id: UUID | None
    submission_id: UUID | None
    draft: OpportunityDraft
    reason: str | None = None


class ItemOpportunityService:
    """Owner-only: research, link, unlink; approval resolves the links."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        intake: OpportunityIntake,
        catalog: OpportunityService,
        consents: PurposeConsents,
        limiter: RateLimiter,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._intake = intake
        self._catalog = catalog
        self._consents = consents
        self._limiter = limiter
        self._clock = clock

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})

    async def _own_item(self, ctx: AdmissionContext, item_id: UUID) -> None:
        await self._owner(ctx)
        async with self._uow() as uow:
            item = await uow.items.get(item_id)
        if item is None or item.student_id != ctx.user_id:
            raise AdmissionNotFoundError()

    async def lookup(self, ctx: AdmissionContext, query: str, locale: str) -> Lookup:
        """Research one line; needs AI consent and a daily allowance."""
        await self._owner(ctx)
        clean = sanitize_query(query)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        await self._limiter.hit(
            f"admission:opportunity_lookup:{ctx.user_id}",
            limit=LOOKUP_PER_DAY,
            window_seconds=_DAY,
        )
        draft = await self._intake.research(
            ctx,
            clean,
            locale=locale,
            today=self._clock.now().date(),
            taxonomy=await self._catalog.taxonomy(),
        )
        probe = proposal_of(draft) if draft.title else None
        matches: list[Opportunity] = []
        pending = None
        if probe is not None:
            keys, title = _keys_of(probe), _norm(probe.title)
            async with self._uow() as uow:
                published = await uow.opportunities.list_published()
                waiting = await uow.opportunities.list_submissions(
                    status="pending", submitted_by=None
                )
            matches = [o for o in published if _similar(o.draft, keys, title)]
            matches.sort(key=lambda o: not keys & _keys_of(o.draft))
            pending = next((s for s in waiting if keys & _keys_of(s.draft)), None)
        return Lookup(draft, matches[:MAX_MATCHES], pending)

    async def get(
        self, ctx: AdmissionContext, item_id: UUID
    ) -> ItemOpportunityView | None:
        """The linked opportunity of the caller's activity, or None."""
        await self._own_item(ctx, item_id)
        async with self._uow() as uow:
            return await _view(uow.opportunities, item_id)

    async def link_existing(
        self, ctx: AdmissionContext, item_id: UUID, opportunity_id: UUID
    ) -> ItemOpportunityView:
        """Link a published catalog entry."""
        await self._own_item(ctx, item_id)
        async with self._uow() as uow:
            opp = await uow.opportunities.get(opportunity_id)
            if opp is None or opp.archived:
                raise ValidationFailedError(params={"field": "opportunity_id"})
            await uow.opportunities.save_item_link(
                ItemOpportunityLink(item_id, None, opportunity_id)
            )
            await uow.commit()
        return ItemOpportunityView(item_id, "verified", opp.id, None, opp.draft)

    async def link_new(
        self, ctx: AdmissionContext, item_id: UUID, draft: IntakeDraft
    ) -> ItemOpportunityView:
        """Link a proposal: an exact catalog entry, a pending twin, or a new one."""
        await self._own_item(ctx, item_id)
        proposal = proposal_of(draft)
        keys = _keys_of(proposal)
        async with self._uow() as uow:
            published = await uow.opportunities.list_published()
            waiting = await uow.opportunities.list_submissions(
                status="pending", submitted_by=None
            )
        same = next((o for o in published if keys & _keys_of(o.draft)), None)
        if same is not None:
            return await self.link_existing(ctx, item_id, same.id)
        twin = next((s for s in waiting if keys & _keys_of(s.draft)), None)
        if twin is None:
            twin = await self._catalog.submit(ctx, proposal)
        async with self._uow() as uow:
            await uow.opportunities.save_item_link(
                ItemOpportunityLink(item_id, twin.id, None)
            )
            await uow.commit()
        return ItemOpportunityView(item_id, "pending", None, twin.id, twin.draft)

    async def unlink(self, ctx: AdmissionContext, item_id: UUID) -> None:
        """Remove the link (the proposal stays in moderation)."""
        await self._own_item(ctx, item_id)
        async with self._uow() as uow:
            if not await uow.opportunities.delete_item_link(item_id):
                raise AdmissionNotFoundError()
            await uow.commit()


async def _view(
    repo: OpportunityRepository, item_id: UUID
) -> ItemOpportunityView | None:
    link = await repo.item_link(item_id)
    if link is None:
        return None
    if link.opportunity_id is not None:
        opp = await repo.get(link.opportunity_id)
        if opp is not None:
            return ItemOpportunityView(
                item_id, "verified", opp.id, link.submission_id, opp.draft
            )
    sub = await repo.get_submission(link.submission_id) if link.submission_id else None
    if sub is None:
        return None
    if sub.status == "approved" and sub.applied_id is not None:
        opp = await repo.get(sub.applied_id)
        if opp is not None:
            return ItemOpportunityView(item_id, "verified", opp.id, sub.id, opp.draft)
    status: LinkStatus = "rejected" if sub.status == "rejected" else "pending"
    return ItemOpportunityView(item_id, status, None, sub.id, sub.draft, sub.reason)
