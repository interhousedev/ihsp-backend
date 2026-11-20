"""Reach/target/safety of the list, its balance, and AI proposals of new entries."""

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.chooser import ListItem, ListService
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.student_context import student_block
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.classification import (
    LABELS,
    Balance,
    Classification,
    StudentSignals,
    balance,
    classify,
    signals_of,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
)
from app.modules.admission.domain.estimates import estimate
from app.modules.admission.domain.list_brief import BriefCandidate, brief_candidates
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.infrastructure.ai.prompts import list_brief as brief_prompt
from app.modules.admission.infrastructure.ai.prompts import list_suggest as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

_WEEK: Final = 7 * 24 * 3600
_TOKENS: Final = 1200
MAX_CANDIDATES: Final = 60
"""Catalog institutions offered to the model, verified ones first."""


@dataclass(frozen=True, slots=True)
class ClassifiedEntry:
    """One list entry with its label in force."""

    entry_id: UUID
    institution_id: UUID
    classification: Classification


@dataclass(frozen=True, slots=True)
class ListInsights:
    """Labels of every entry and the balance of the list."""

    entries: list[ClassifiedEntry]
    balance: Balance
    profile_used: bool


@dataclass(frozen=True, slots=True)
class ListSuggestion:
    """A proposed institution, not yet on the list; nothing is stored."""

    institution: CatalogInstitution
    label: str
    reason: str


@dataclass(frozen=True, slots=True)
class BriefSuggestion:
    """A candidate the brief recommends: its computed role and the model's reason."""

    candidate: BriefCandidate
    reason: str


@dataclass(frozen=True, slots=True)
class ListBrief:
    """The written brief: the model's text, the computed balance and candidates."""

    headline: str
    diagnosis: str
    next_steps: list[str]
    suggestions: list[BriefSuggestion]
    balance: Balance
    entries: int


class ListPlanService:
    """Classification and balance for readers, AI proposals for the owner."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        lists: ListService,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        weekly_limit: QuotaOf,
        prompts: PromptSource,
        search: StudentDataSearch | None = None,
    ) -> None:
        """Keep the collaborators and the reader of the soft weekly limit."""
        self._uow = uow_factory
        self._access = access
        self._lists = lists
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._limit = weekly_limit
        self._prompts = prompts
        self._search = search

    async def _signals(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> StudentSignals | None:
        """Profile signals, only when the viewer may read the profile."""
        res = await self._access.resolve(ctx, student_id)
        if not (res.owner or Permission.PROFILE_READ in res.permissions):
            return None
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
        return signals_of(profile.answers) if profile is not None else StudentSignals()

    async def insights(self, ctx: AdmissionContext, student_id: UUID) -> ListInsights:
        """Labels and balance of a list the caller may read."""
        items = await self._lists.view(ctx, student_id)
        signals = await self._signals(ctx, student_id)
        year = self._clock.now().year
        out = [self._classify(i, signals, year) for i in items]
        return ListInsights(
            out,
            balance(c.classification.effective for c in out),
            signals is not None,
        )

    @staticmethod
    def _classify(
        item: ListItem, signals: StudentSignals | None, year: int
    ) -> ClassifiedEntry:
        e = item.entry
        est = estimate(item.institution, e.affordability_status, year)
        return ClassifiedEntry(
            e.id,
            item.institution.id,
            classify(
                item.institution,
                est.label,
                signals,
                bucket=e.bucket,
                override=e.label_override,
            ),
        )

    async def suggest(self, ctx: AdmissionContext, locale: str) -> list[ListSuggestion]:
        """Ask the model for institutions that would balance the owner's list."""
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        current = await self.insights(ctx, ctx.user_id)
        on_list = {c.institution_id for c in current.entries}
        async with self._uow() as uow:
            catalog = await uow.catalog.institutions()
            names = {
                c.institution_id: inst.name
                for c in current.entries
                if (inst := await uow.catalog.institution(c.institution_id))
            }
        pool = sorted(
            (i for i in catalog if i.id not in on_list),
            key=lambda i: (not i.verified, i.name.casefold()),
        )[:MAX_CANDIDATES]
        if not pool:
            return []
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:list_suggest:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        year = self._clock.now().year
        lines = [f"Language: {locale}", f"Balance: {current.balance.status}"]
        lines += [
            f"[on_list] {names.get(c.institution_id, '')} "
            f"label={c.classification.effective or 'unknown'}"
            for c in current.entries
        ]
        lines += await student_block(
            self._search,
            ctx.user_id,
            [names.get(c.institution_id, "") for c in current.entries][:1]
            + ["intended major", "budget"],
            ("profile", "course", "grade", "test_score", "list", "item"),
        )
        for n, inst in enumerate(pool, start=1):
            lines.append(
                f"[candidate:{n}] {inst.name} ({inst.country}) "
                f"rate_label={estimate(inst, 'unknown', year).label}"
            )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_LIST_SUGGEST,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_LIST_SUGGEST, "system", locale)
            ),
            user=delimit(lines),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        return self._clean(data, pool)

    async def brief(self, ctx: AdmissionContext, locale: str) -> ListBrief:
        """Write the brief on the owner's list balance (AI consent and limit apply).

        The candidates (institutions off the list that fit as safety or target)
        are computed from catalog data and the student's profile; the model picks
        among them and writes the diagnosis, reasons and next steps.
        """
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        current = await self.insights(ctx, ctx.user_id)
        signals = await self._signals(ctx, ctx.user_id)
        async with self._uow() as uow:
            catalog = await uow.catalog.institutions()
        names = {i.id: i.name for i in catalog}
        pool = brief_candidates(
            catalog,
            {c.institution_id for c in current.entries},
            current.balance,
            signals,
            self._clock.now().year,
        )
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:list_brief:{ctx.user_id}",
                limit=limit,
                window_seconds=_WEEK,
            )
        b = current.balance
        lines = [
            f"Language: {locale}",
            f"Balance: {b.status}; reach={b.reach} target={b.target} "
            f"safety={b.safety} unlabelled={b.unlabelled}",
        ]
        lines += [
            f"[on_list] {names.get(c.institution_id, '')} "
            f"label={c.classification.effective or 'unknown'}"
            for c in current.entries
        ]
        lines += await student_block(
            self._search,
            ctx.user_id,
            ["intended major", "budget", "grades"],
            ("profile", "course", "grade", "test_score", "list"),
        )
        for n, c in enumerate(pool, start=1):
            rate = (
                f"admit_rate={c.admit_rate.percent:.1f}% ({c.admit_rate.scope})"
                if c.admit_rate
                else "admit_rate=unknown (not published: a cheaper option to check, "
                "do not state a chance)"
            )
            lines.append(
                f"[candidate:{n}] {c.institution.name} "
                f"({c.institution.country}) role={c.role} {rate}"
            )
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_LIST_BRIEF,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_LIST_BRIEF, "system", locale)
            ),
            user=delimit(lines),
            schema_name=brief_prompt.SCHEMA_NAME,
            schema=brief_prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        return self._clean_brief(data, pool, b, len(current.entries))

    @staticmethod
    def _clean_brief(
        data: dict[str, Any],
        pool: list[BriefCandidate],
        balance_: Balance,
        entries: int,
    ) -> ListBrief:
        """Keep text within its limits and only distinct, listed candidates."""

        def text(key: str, limit: int) -> str:
            return nfc(plain(str(data.get(key, "")))).strip()[:limit]

        seen: set[int] = set()
        picks: list[BriefSuggestion] = []
        for raw in data.get("suggestions", []):
            if len(picks) >= brief_prompt.MAX_SUGGESTED:
                break
            try:
                n = int(raw.get("candidate", 0))
            except (TypeError, ValueError, AttributeError):
                continue
            if not 1 <= n <= len(pool) or n in seen:
                continue
            seen.add(n)
            reason = nfc(plain(str(raw.get("reason", "")))).strip()
            picks.append(
                BriefSuggestion(pool[n - 1], reason[: brief_prompt.REASON_MAX])
            )
        steps = [
            nfc(plain(str(s))).strip()[: brief_prompt.STEP_MAX]
            for s in data.get("next_steps", [])
        ]
        return ListBrief(
            text("headline", brief_prompt.HEADLINE_MAX),
            text("diagnosis", brief_prompt.DIAGNOSIS_MAX),
            [s for s in steps if s][: brief_prompt.MAX_STEPS],
            picks,
            balance_,
            entries,
        )

    @staticmethod
    def _clean(
        data: dict[str, Any], pool: list[CatalogInstitution]
    ) -> list[ListSuggestion]:
        """Keep distinct proposals that name a listed candidate."""
        seen: set[int] = set()
        out: list[ListSuggestion] = []
        for raw in data.get("suggestions", [])[: prompt.MAX_SUGGESTED]:
            try:
                n = int(raw.get("candidate", 0))
            except (TypeError, ValueError):
                continue
            if not 1 <= n <= len(pool) or n in seen:
                continue
            label = str(raw.get("label", ""))
            if label not in LABELS:
                continue
            seen.add(n)
            reason = nfc(plain(str(raw.get("reason", "")))).strip()
            out.append(ListSuggestion(pool[n - 1], label, reason[: prompt.REASON_MAX]))
        return out
