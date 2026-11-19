"""The admission assistant's side of the unified AI chat (assistant `admission`).

The chat, streaming and tool loop live in the AI module; this service answers its
tools for the applicant: a read of the whole application, the FAQ search and
one-click suggestions of courses, opportunities, scholarships and universities.
"""

import unicodedata
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.chooser import CatalogService, ListService
from app.modules.admission.application.courses import CourseService
from app.modules.admission.application.kb import KbService
from app.modules.admission.application.opportunities import (
    CatalogFilter,
    OpportunityService,
)
from app.modules.admission.domain.assistant import starter_questions
from app.modules.admission.domain.chooser import CatalogFilters
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.kb import snippet
from app.modules.admission.ports.ai import QuotaOf
from app.modules.admission.ports.assistant import AssistantData
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.courses import CourseSources
from app.shared.actor import Actor
from app.shared.contracts.admission_assistant import (
    COURSE_LIMIT_MAX,
    COURSE_SUMMARY_MAX,
    COURSE_TITLE_MAX,
    SUGGESTION_KINDS,
    CourseHit,
    FaqHit,
    SuggestionCard,
    SuggestionKind,
)
from app.shared.rate_limit import RateLimiter

_DAY: Final = 24 * 3600
_LIMIT_MAX: Final = 10
_REASON_MAX: Final = 300


def _reason(*parts: str | None) -> str:
    return " · ".join(p.strip() for p in parts if p and p.strip())[:_REASON_MAX]


def _plain(text: str | None, limit: int) -> str:
    """Clean third-party course text.

    No control or format characters, one line, cut to `limit`. It reaches the
    model only as data.
    """
    kept = (
        " " if unicodedata.category(ch).startswith(("C", "Z")) else ch
        for ch in text or ""
    )
    return " ".join("".join(kept).split())[:limit]


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise AdmissionNotFoundError() from None


class AssistantService:
    """Implements `AdmissionAssistantApi` for the AI module's tools."""

    def __init__(
        self,
        access: AccessPolicy,
        data: AssistantData,
        consents: PurposeConsents,
        limiter: RateLimiter,
        quota: QuotaOf,
        kb: KbService,
        opportunities: OpportunityService,
        lists: ListService,
        catalog: CatalogService,
        courses: CourseService,
        course_sources: CourseSources,
        actor_resolver: ResolveAdmissionActor,
    ) -> None:
        """Keep the collaborators."""
        self._access = access
        self._data = data
        self._consents = consents
        self._limiter = limiter
        self._quota = quota
        self._kb = kb
        self._opportunities = opportunities
        self._lists = lists
        self._catalog = catalog
        self._courses = courses
        self._sources = course_sources
        self._resolve = actor_resolver

    def suggestions(self, path: str, locale: str) -> list[str]:
        """Three starter questions of the screen, from the configuration."""
        return starter_questions(path, locale)

    async def _ctx(self, actor: Actor) -> AdmissionContext:
        ctx = await self._resolve.execute(actor)
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "assistant:use"})
        if not (await self._access.resolve(ctx, ctx.user_id)).owner:
            raise AdmissionForbiddenError(params={"permission": "assistant:use"})
        return ctx

    async def require_assistant(self, actor: Actor) -> None:
        """Raise unless the actor is an applicant who owns an application."""
        await self._ctx(actor)

    async def admit_turn(self, actor: Actor) -> None:
        """Check the AI consent and count one turn against the daily quota."""
        ctx = await self._ctx(actor)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        limit = await self._quota(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:assistant:{ctx.user_id}", limit=limit, window_seconds=_DAY
            )

    async def application(self, actor: Actor) -> dict[str, Any]:
        """The caller's whole application as plain JSON-ready data."""
        uid = (await self._ctx(actor)).user_id
        d = self._data
        return {
            "profile": await d.profile(uid),
            "activities_and_honors": await d.items(uid),
            "essays": await d.essays(uid),
            "universities": await d.universities(uid),
            "deadlines": await d.deadlines(uid),
            "test_scores": await d.test_scores(uid),
            "memory_notes": await d.memory_notes(uid),
            "courses": await d.courses(uid),
            "documents": await d.documents(uid),
            "tasks": await d.tasks(uid),
        }

    async def search_faq(
        self, actor: Actor, query: str, locale: str | None, limit: int
    ) -> list[FaqHit]:
        """Published FAQ articles matching the query, the locale's first."""
        await self._ctx(actor)
        found = await self._kb.published(query, locale, max(1, min(limit, _LIMIT_MAX)))
        return [
            FaqHit(
                id=str(a.id),
                title=a.title,
                snippet=snippet(a.body),
                locale=a.locale,
                link=f"/faq/?id={a.id}",
                tags=list(a.tags),
            )
            for a in found
        ]

    async def find_courses(
        self, actor: Actor, query: str, limit: int
    ) -> list[CourseHit]:
        """LMS courses the caller may see (never locked ones), `enrolled` marked."""
        ctx = await self._ctx(actor)
        limit = max(1, min(limit, COURSE_LIMIT_MAX))
        found = await self._sources.lms_find(ctx.actor, query.strip() or None, limit)
        return [
            CourseHit(
                id=c.id,
                title=_plain(c.title, COURSE_TITLE_MAX),
                summary=_plain(c.summary, COURSE_SUMMARY_MAX),
                url=c.url,
                enrolled=c.enrolled,
            )
            for c in found
        ][:limit]

    async def suggest(
        self, actor: Actor, kind: SuggestionKind, query: str, limit: int
    ) -> list[SuggestionCard]:
        """Cards of things the caller does not have yet, best matches first."""
        ctx = await self._ctx(actor)
        if kind not in SUGGESTION_KINDS:
            raise AdmissionNotFoundError()
        limit = max(1, min(limit, _LIMIT_MAX))
        q = query.strip() or None
        if kind == "course":
            have = {c.source_ref for c in await self._sources.lms_courses(ctx.actor)}
            found = await self._sources.lms_catalog(ctx.actor, q)
            return [
                self._course_card(c.source_ref, c.title, c.provider)
                for c in found
                if c.source_ref and c.source_ref not in have
            ][:limit]
        if kind == "university":
            listed = {
                u.get("institution_id")
                for u in await self._data.universities(ctx.user_id)
            }
            page = await self._catalog.search(CatalogFilters(q=q), limit=limit * 2)
            return [
                self._university_card(i) for i in page.items if str(i.id) not in listed
            ][:limit]
        f = CatalogFilter(
            query=q, kind="scholarship" if kind == "scholarship" else None
        )
        found_o = await self._opportunities.browse(f)
        return [
            self._opportunity_card(kind, o)
            for o in found_o
            if (o.draft.kind == "scholarship") == (kind == "scholarship")
        ][:limit]

    async def describe(
        self, actor: Actor, kind: SuggestionKind, item_id: str
    ) -> SuggestionCard:
        """The card of one item, for the approval preview."""
        ctx = await self._ctx(actor)
        if kind == "course":
            for c in await self._sources.lms_catalog(ctx.actor, None):
                if c.source_ref == item_id:
                    return self._course_card(c.source_ref, c.title, c.provider)
            raise AdmissionNotFoundError()
        if kind == "university":
            return self._university_card(
                await self._catalog.institution(_uuid(item_id))
            )
        if kind in ("opportunity", "scholarship"):
            o = await self._opportunities.get(_uuid(item_id))
            return self._opportunity_card(kind, o)
        raise AdmissionNotFoundError()

    async def add_suggestion(
        self, actor: Actor, kind: SuggestionKind, item_id: str
    ) -> SuggestionCard:
        """Add the item: enroll in a course, plan an opportunity, list a university."""
        card = await self.describe(actor, kind, item_id)
        ctx = await self._ctx(actor)
        ref = _uuid(item_id)
        if kind == "course":
            await self._sources.lms_enroll(ctx.actor, ref)
            await self._courses.add_from_lms(ctx, ref)
        elif kind == "university":
            await self._lists.add(ctx, ref)
        else:
            await self._opportunities.save_to_plan(
                ctx, ref, planned_grade=None, note=None
            )
        return card

    @staticmethod
    def _course_card(ref: str, title: str, provider: str | None) -> SuggestionCard:
        return SuggestionCard(
            type="course",
            id=ref,
            title=title,
            reason=_reason(provider),
            link=f"/courses/?lms={ref}",
        )

    @staticmethod
    def _university_card(inst: Any) -> SuggestionCard:
        return SuggestionCard(
            type="university",
            id=str(inst.id),
            title=inst.name,
            reason=_reason(inst.city, inst.country),
            link=f"/chooser/institution/?id={inst.id}",
        )

    @staticmethod
    def _opportunity_card(kind: SuggestionKind, o: Any) -> SuggestionCard:
        d = o.draft
        return SuggestionCard(
            type=kind,
            id=str(o.id),
            title=d.title,
            reason=_reason(d.provider, d.summary, d.kind),
            link=f"/opportunities/?id={o.id}",
        )
