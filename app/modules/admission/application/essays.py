"""Essay workspace: drafts with autosave, versions, ideas, plan and an AI coach.

Only the owner edits. Staff in scope read the versions the student shared, never
the live draft, notes, plan or ideas. The coach asks questions and comments; it
never writes the essay.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import resolve_targets
from app.modules.admission.application.essay_review_core import (
    EssayCheck,
    Feedback,
    SentenceNote,
    _get,
    _line,
    _lines,
    brief,
    check_from,
    check_key,
    check_payload,
    essay_input,
    run_check,
    run_feedback,
)
from app.modules.admission.application.items import items_summary
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.student_context import student_block
from app.modules.admission.application.words import delimit
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
    EssayTooShortError,
    ItemLimitError,
)
from app.modules.admission.domain.essay_flow import PromptTarget
from app.modules.admission.domain.essay_reviews import StoredReview
from app.modules.admission.domain.essays import (
    KINDS,
    LINK_KINDS,
    MAX_ESSAYS,
    MAX_IDEAS,
    SNAPSHOT_INTERVAL,
    VERSION_NAME_MAX,
    Essay,
    EssayIdea,
    EssayLink,
    EssayVersion,
    PlanSection,
    word_count,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.questions import BY_ID
from app.modules.admission.infrastructure.ai.prompts import essays as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.modules.admission.ports.essays import EssayText
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

EDITABLE: Final = frozenset(
    {
        "kind",
        "title",
        "prompt_text",
        "word_limit",
        "list_entry_id",
        "body",
        "notes",
        "plan",
        "links",
        "status",
        "targets",
    }
)
IDEA_EDITABLE: Final = frozenset({"body", "essay_id", "tags", "status", "sort_order"})
_DAY: Final = 24 * 3600
CHECK_MIN_WORDS: Final = 50
_TOKENS: Final = 1200
_BODY_TO_MODEL: Final = 12000


@dataclass(frozen=True, slots=True)
class SharedEssay:
    """What staff see: the brief and the shared versions, newest first."""

    essay: Essay
    versions: list[EssayVersion]


def _forbidden() -> AdmissionForbiddenError:
    return AdmissionForbiddenError(params={"permission": "essays:edit"})


class EssayService:
    """The student's essays; staff read shared versions in scope."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the transaction factory, the access policy and the clock."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise _forbidden()

    @staticmethod
    async def _own(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, essay_id: UUID
    ) -> Essay:
        essay = await uow.essays.get(essay_id)
        if essay is None or essay.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return essay

    @staticmethod
    async def _own_idea(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, idea_id: UUID
    ) -> EssayIdea:
        idea = await uow.essays.get_idea(idea_id)
        if idea is None or idea.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return idea

    @staticmethod
    async def _check(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, essay: Essay
    ) -> None:
        """Validate fields and every reference against the owner's data."""
        if essay.kind not in KINDS:
            raise CharLimitError(params={"field": "kind", "limit": 0, "count": 0})
        essay.validate()
        essay.targets = await resolve_targets(uow, essay.targets)
        if essay.list_entry_id is not None:
            entry = await uow.shortlist.entry(essay.list_entry_id)
            if entry is None or entry.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
        elif essay.kind == "supplemental" and not essay.targets:
            raise CharLimitError(
                params={"field": "list_entry_id", "limit": 1, "count": 0}
            )
        for link in essay.links:
            await _check_link(uow, ctx, link)

    async def mine(self, ctx: AdmissionContext) -> list[Essay]:
        """Return the owner's essays."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await uow.essays.list_for(ctx.user_id)

    async def get(self, ctx: AdmissionContext, essay_id: UUID) -> Essay:
        """Return one of the owner's essays."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await self._own(uow, ctx, essay_id)

    async def create(self, ctx: AdmissionContext, fields: Mapping[str, Any]) -> Essay:
        """Create an essay; at most MAX_ESSAYS per student."""
        await self._owner(ctx)
        values = _coerce({k: v for k, v in fields.items() if k in EDITABLE})
        now = self._clock.now()
        essay = Essay(
            id=new_id(),
            student_id=ctx.user_id,
            created_at=now,
            updated_at=now,
            **values,
        )
        async with self._uow() as uow:
            if len(await uow.essays.list_for(ctx.user_id)) >= MAX_ESSAYS:
                raise ItemLimitError(params={"kind": "essay", "limit": MAX_ESSAYS})
            await self._check(uow, ctx, essay)
            saved = await uow.essays.add(essay)
            await uow.commit()
            return saved

    async def save(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        lock_version: int,
        fields: Mapping[str, Any],
    ) -> Essay:
        """Autosave: compare-and-set on lock_version; snapshot on an interval."""
        await self._owner(ctx)
        values = _coerce({k: v for k, v in fields.items() if k in EDITABLE})
        now = self._clock.now()
        async with self._uow() as uow:
            current = await self._own(uow, ctx, essay_id)
            essay = replace(
                current, lock_version=lock_version, updated_at=now, **values
            )
            await self._check(uow, ctx, essay)
            snapshot = await self._due(uow, current, essay, now)
            if snapshot:
                essay.current_version = current.current_version + 1
                essay.last_snapshot_at = now
            saved = await uow.essays.update(essay)
            if snapshot:
                await uow.essays.add_version(
                    _version(saved, ctx.user_id, "interval", None, now)
                )
            await uow.commit()
            return saved

    @staticmethod
    async def _due(
        uow: AdmissionUnitOfWork, before: Essay, after: Essay, now: Any
    ) -> bool:
        if after.body == before.body or not after.body.strip():
            return False
        last = before.last_snapshot_at
        if last is not None and now - last < SNAPSHOT_INTERVAL:
            return False
        latest = await uow.essays.version(before.id, before.current_version)
        return latest is None or latest.body != after.body

    async def delete(self, ctx: AdmissionContext, essay_id: UUID) -> None:
        """Delete the essay and its versions; its ideas stay, unlinked."""
        await self._owner(ctx)
        async with self._uow() as uow:
            await self._own(uow, ctx, essay_id)
            await uow.essays.delete(essay_id)
            await uow.commit()

    async def snapshot(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        lock_version: int,
        name: str | None = None,
    ) -> EssayVersion:
        """Save the live draft as a named version on the student's request."""
        await self._owner(ctx)
        name = nfc(name).strip()[:VERSION_NAME_MAX] if name else None
        now = self._clock.now()
        async with self._uow() as uow:
            current = await self._own(uow, ctx, essay_id)
            essay = replace(
                current,
                lock_version=lock_version,
                current_version=current.current_version + 1,
                last_snapshot_at=now,
                updated_at=now,
            )
            saved = await uow.essays.update(essay)
            version = await uow.essays.add_version(
                _version(saved, ctx.user_id, "explicit", name or None, now)
            )
            await uow.commit()
            return version

    async def versions(
        self, ctx: AdmissionContext, essay_id: UUID
    ) -> list[EssayVersion]:
        """Return all versions of the owner's essay, newest first."""
        await self._owner(ctx)
        async with self._uow() as uow:
            await self._own(uow, ctx, essay_id)
            return await uow.essays.versions(essay_id)

    async def restore(
        self, ctx: AdmissionContext, essay_id: UUID, version: int, lock_version: int
    ) -> Essay:
        """Bring an old version back; the current draft is kept as a version."""
        await self._owner(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            current = await self._own(uow, ctx, essay_id)
            old = await uow.essays.version(essay_id, version)
            if old is None:
                raise AdmissionNotFoundError()
            latest = await uow.essays.version(essay_id, current.current_version)
            keep = bool(current.body.strip()) and (
                latest is None or latest.body != current.body
            )
            number = current.current_version + (2 if keep else 1)
            essay = replace(
                current,
                body=old.body,
                lock_version=lock_version,
                current_version=number,
                last_snapshot_at=now,
                updated_at=now,
            )
            saved = await uow.essays.update(essay)
            if keep:
                await uow.essays.add_version(
                    _version(
                        replace(current, current_version=number - 1),
                        ctx.user_id,
                        "explicit",
                        None,
                        now,
                    )
                )
            await uow.essays.add_version(
                _version(saved, ctx.user_id, "restore", None, now)
            )
            await uow.commit()
            return saved

    async def share(
        self, ctx: AdmissionContext, essay_id: UUID, version: int, shared: bool
    ) -> EssayVersion:
        """Share or unshare one version with staff in scope."""
        await self._owner(ctx)
        async with self._uow() as uow:
            await self._own(uow, ctx, essay_id)
            out = await uow.essays.set_shared(essay_id, version, shared)
            if out is None:
                raise AdmissionNotFoundError()
            await uow.commit()
            return out

    async def list_shared(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[SharedEssay]:
        """Staff: the student's essays with at least one shared version."""
        await self._access.require(
            ctx, student_id, Permission.ESSAYS_READ, object_type="essay"
        )
        async with self._uow() as uow:
            out: list[SharedEssay] = []
            for essay in await uow.essays.list_for(student_id):
                shared = [v for v in await uow.essays.versions(essay.id) if v.shared]
                if shared:
                    out.append(SharedEssay(_brief(essay), shared))
            return out

    async def shared_view(self, ctx: AdmissionContext, essay_id: UUID) -> SharedEssay:
        """Staff (or the owner): one essay with its shared versions only."""
        async with self._uow() as uow:
            essay = await uow.essays.get(essay_id)
        if essay is None:
            raise AdmissionNotFoundError()
        try:
            await self._access.require(
                ctx,
                essay.student_id,
                Permission.ESSAYS_READ,
                object_type="essay",
                object_id=essay_id,
            )
        except AdmissionForbiddenError:
            raise AdmissionNotFoundError() from None
        async with self._uow() as uow:
            shared = [v for v in await uow.essays.versions(essay_id) if v.shared]
        if not shared:
            raise AdmissionNotFoundError()
        return SharedEssay(_brief(essay), shared)

    async def ideas(self, ctx: AdmissionContext) -> list[EssayIdea]:
        """Return the owner's ideas board."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await uow.essays.ideas_for(ctx.user_id)

    async def add_idea(
        self, ctx: AdmissionContext, fields: Mapping[str, Any]
    ) -> EssayIdea:
        """Pin a new idea; at most MAX_IDEAS."""
        await self._owner(ctx)
        values = _coerce_idea({k: v for k, v in fields.items() if k in IDEA_EDITABLE})
        now = self._clock.now()
        idea = EssayIdea(
            id=new_id(),
            student_id=ctx.user_id,
            created_at=now,
            updated_at=now,
            **{"body": "", **values},
        )
        idea.validate()
        async with self._uow() as uow:
            if len(await uow.essays.ideas_for(ctx.user_id)) >= MAX_IDEAS:
                raise ItemLimitError(params={"kind": "idea", "limit": MAX_IDEAS})
            if idea.essay_id is not None:
                await self._own(uow, ctx, idea.essay_id)
            saved = await uow.essays.add_idea(idea)
            await uow.commit()
            return saved

    async def update_idea(
        self,
        ctx: AdmissionContext,
        idea_id: UUID,
        lock_version: int,
        fields: Mapping[str, Any],
    ) -> EssayIdea:
        """Edit an idea (compare-and-set on lock_version)."""
        await self._owner(ctx)
        values = _coerce_idea({k: v for k, v in fields.items() if k in IDEA_EDITABLE})
        async with self._uow() as uow:
            current = await self._own_idea(uow, ctx, idea_id)
            idea = replace(
                current,
                lock_version=lock_version,
                updated_at=self._clock.now(),
                **values,
            )
            idea.validate()
            if idea.essay_id is not None:
                await self._own(uow, ctx, idea.essay_id)
            saved = await uow.essays.update_idea(idea)
            await uow.commit()
            return saved

    async def delete_idea(self, ctx: AdmissionContext, idea_id: UUID) -> None:
        """Remove an idea."""
        await self._owner(ctx)
        async with self._uow() as uow:
            await self._own_idea(uow, ctx, idea_id)
            await uow.essays.delete_idea(idea_id)
            await uow.commit()


def _brief(essay: Essay) -> Essay:
    """Strip the private parts of an essay before staff see it."""
    return replace(essay, body="", notes="", plan=(), links=())


def _version(
    essay: Essay, by: UUID, source: Any, name: str | None, now: Any
) -> EssayVersion:
    return EssayVersion(
        id=new_id(),
        essay_id=essay.id,
        version=essay.current_version,
        body=essay.body,
        created_by=by,
        source=source,
        name=name,
        word_count=word_count(essay.body),
        created_at=now,
    )


def _text(value: Any) -> str:
    return nfc(str(value or ""))


def _coerce(values: dict[str, Any]) -> dict[str, Any]:
    """Normalise request values into domain types."""
    out = dict(values)
    for key in ("title", "prompt_text", "body", "notes"):
        if key in out:
            out[key] = _text(out[key])
    if "title" in out:
        out["title"] = out["title"].strip()
    if "plan" in out:
        out["plan"] = tuple(
            PlanSection(_text(_get(s, "heading")).strip(), _text(_get(s, "note")))
            for s in out["plan"] or ()
        )
    if "links" in out:
        out["links"] = tuple(
            EssayLink(_get(link, "kind"), str(_get(link, "ref")))
            for link in out["links"] or ()
        )
    if "targets" in out:
        out["targets"] = tuple(_target(t) for t in out["targets"] or ())
    return out


def _target(raw: Any) -> PromptTarget:
    """A request target: only the owner and position count, the text comes later."""
    if isinstance(raw, PromptTarget):
        return raw
    owner = _get(raw, "institution_id")
    return PromptTarget(
        None if owner is None else UUID(str(owner)), int(_get(raw, "position")), ""
    )


async def _check_link(
    uow: AdmissionUnitOfWork, ctx: AdmissionContext, link: EssayLink
) -> None:
    """A link must name a profile question or one of the owner's items."""
    if link.kind not in LINK_KINDS:
        raise AdmissionNotFoundError()
    if link.kind == "profile_answer":
        if link.ref not in BY_ID:
            raise AdmissionNotFoundError()
        return
    try:
        item = await uow.items.get(UUID(link.ref))
    except ValueError:
        raise AdmissionNotFoundError() from None
    if item is None or item.student_id != ctx.user_id:
        raise AdmissionNotFoundError()


def _coerce_idea(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    if "body" in out:
        out["body"] = _text(out["body"]).strip()
    if "tags" in out:
        seen: dict[str, None] = {}
        for tag in out["tags"] or ():
            clean = _text(tag).strip()
            if clean:
                seen.setdefault(clean, None)
        out["tags"] = tuple(seen)
    return out


@dataclass(frozen=True, slots=True)
class OutlineSection:
    """A proposed section; the student decides whether to keep it."""

    heading: str
    note: str
    share_percent: int


@dataclass(frozen=True)
class LifeStoryReading:
    """What a free life story shows about the student."""

    drivers: list[str]
    support: list[str]
    leave_out: list[str]
    ideas: list[str]


@dataclass(frozen=True, slots=True)
class Expansion:
    """How an idea could fit, and angles to think about."""

    fit: str
    angles: list[str]


class EssayCoach:
    """AI helpers for the owner: questions, angles, outline, feedback.

    Each call needs the `admission_ai` consent and fits a soft daily quota.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        daily_limit: QuotaOf,
        prompts: PromptSource,
        search: StudentDataSearch | None = None,
        *,
        cipher: EssayCipher,
    ) -> None:
        """Keep the collaborators and the reader of the soft daily limit."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._limit = daily_limit
        self._prompts = prompts
        self._search = search
        self._cipher = cipher

    async def _gate(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise _forbidden()
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})

    async def _ask(
        self,
        ctx: AdmissionContext,
        name: str,
        locale: str,
        lines: list[str],
        max_tokens: int = _TOKENS,
    ) -> dict[str, Any]:
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:essay_coach:{ctx.user_id}",
                limit=limit,
                window_seconds=_DAY,
            )
        schema_name, schema = prompt.SCHEMAS[name]
        data, _ = await self._ai.json(
            task=AiTask.ADMIT_ESSAY_COACH,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_ESSAY_COACH, name, locale)
            ),
            user=delimit([f"Language: {locale}", *lines]),
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
        )
        return data

    async def _context(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext
    ) -> list[str]:
        words = await uow.items.words(ctx.user_id)
        items = await uow.items.list_for(ctx.user_id)
        metrics = await uow.items.metrics_for([i.id for i in items])
        lines = []
        if words is not None and words.words:
            lines.append(f"Words: {', '.join(words.words)}")
        lines += [f"[item] {i}" for i in items_summary(items, metrics)]
        return lines

    async def _recall(
        self, ctx: AdmissionContext, queries: list[str], skip: UUID | None = None
    ) -> list[str]:
        """The student's own data that relates to the queries."""
        lines = await student_block(
            self._search,
            ctx.user_id,
            queries,
            ("item", "essay", "profile", "task", "course", "grade"),
        )
        return [ln for ln in lines if skip is None or f":{skip}]" not in ln]

    @staticmethod
    def _brief(essay: Essay) -> list[str]:
        return brief(essay_input(essay))

    async def _essay(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, essay_id: UUID
    ) -> Essay:
        essay = await uow.essays.get(essay_id)
        if essay is None or essay.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return essay

    async def brainstorm(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> list[str]:
        """Return questions that help the student find their own story."""
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            lines = self._brief(essay) + await self._context(uow, ctx)
            ideas = await uow.essays.ideas_for(ctx.user_id)
        lines += [f"[idea] {i.body}" for i in ideas if i.status != "drop"][:20]
        lines += await self._recall(ctx, [essay.prompt_text, essay.title], essay.id)
        data = await self._ask(ctx, "brainstorm", locale, lines)
        return _lines(data.get("questions"), prompt.MAX_QUESTIONS)

    async def expand(
        self, ctx: AdmissionContext, idea_id: UUID, locale: str
    ) -> Expansion:
        """Suggest how one idea could fit and which angles to explore."""
        await self._gate(ctx)
        async with self._uow() as uow:
            idea = await uow.essays.get_idea(idea_id)
            if idea is None or idea.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            lines = await self._context(uow, ctx)
            if idea.essay_id is not None:
                essay = await uow.essays.get(idea.essay_id)
                if essay is not None and essay.student_id == ctx.user_id:
                    lines = self._brief(essay) + lines
        lines.append(f"Idea: {idea.body}")
        lines += await self._recall(ctx, [idea.body, *idea.tags])
        if idea.tags:
            lines.append(f"Tags: {', '.join(idea.tags)}")
        data = await self._ask(ctx, "expand", locale, lines)
        return Expansion(
            _line(data.get("fit")), _lines(data.get("angles"), prompt.MAX_POINTS)
        )

    async def outline(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> list[OutlineSection]:
        """Propose outline sections from the prompt, kept ideas and notes."""
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            lines = self._brief(essay) + await self._context(uow, ctx)
            ideas = await uow.essays.ideas_for(ctx.user_id)
        lines += [
            f"[idea:{i.status}] {i.body}"
            for i in ideas
            if i.status != "drop" and i.essay_id in (None, essay.id)
        ][:20]
        if essay.notes:
            lines.append(f"Notes: {essay.notes}")
        lines += [f"[section] {s.heading}: {s.note}" for s in essay.plan]
        lines += await self._recall(ctx, [essay.prompt_text, essay.title], essay.id)
        data = await self._ask(ctx, "outline", locale, lines)
        out: list[OutlineSection] = []
        for raw in (data.get("sections") or [])[: prompt.MAX_SECTIONS]:
            heading = _line(_get(raw, "heading"))
            if not heading:
                continue
            try:
                share = int(_get(raw, "share_percent") or 0)
            except (TypeError, ValueError):
                share = 0
            out.append(
                OutlineSection(
                    heading[:120], _line(_get(raw, "note")), min(max(share, 0), 100)
                )
            )
        return out

    async def _hit(self, ctx: AdmissionContext) -> None:
        limit = await self._limit(ctx.user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:essay_coach:{ctx.user_id}",
                limit=limit,
                window_seconds=_DAY,
            )

    async def feedback(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> Feedback:
        """Comment on the draft against its prompt and word limit."""
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        if not essay.body.strip():
            raise CharLimitError(params={"field": "body", "limit": 1, "count": 0})
        context = await self._recall(ctx, [essay.prompt_text, essay.title], essay.id)
        await self._hit(ctx)
        out, _ = await run_feedback(
            self._ai,
            self._prompts,
            essay=essay_input(essay),
            locale=locale,
            context=context,
        )
        return out

    async def check(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> EssayCheck:
        """Score the draft on six dimensions against its prompt and store it."""
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        count = essay.word_count
        if count < CHECK_MIN_WORDS:
            raise EssayTooShortError(params={"min": CHECK_MIN_WORDS, "count": count})
        text = essay_input(essay)
        await self._hit(ctx)
        result, model = await run_check(
            self._ai, self._prompts, essay=text, locale=locale
        )
        digest = await self._cipher.digest(
            ctx.user_id, "essay_review", check_key(text, locale)
        )
        async with self._uow() as uow:
            await uow.essay_reviews.save(
                StoredReview(
                    id=new_id(),
                    essay_id=essay.id,
                    student_id=ctx.user_id,
                    kind="check",
                    institution_id=None,
                    input_digest=digest,
                    payload=check_payload(result),
                    model=model,
                    prompt_ref=f"{AiTask.ADMIT_ESSAY_COACH.value}/check",
                    created_at=self._clock.now(),
                )
            )
            await uow.commit()
        return result

    async def latest_check(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str
    ) -> tuple[EssayCheck, bool, datetime]:
        """The last stored check, whether the essay changed since, and its time.

        Never calls the model and never spends quota; a foreign essay is 404.
        """
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
            stored = await uow.essay_reviews.latest(essay.id, "check", None)
        if stored is None:
            raise AdmissionNotFoundError()
        digest = await self._cipher.digest(
            ctx.user_id, "essay_review", check_key(essay_input(essay), locale)
        )
        stale = stored.input_digest != digest
        return check_from(stored.payload), stale, stored.created_at

    async def review(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        locale: str,
        mode: str,
        excerpt: str,
    ) -> Feedback:
        """Review the draft in a mode: overall, by sentence, both or one excerpt."""
        if mode == "overall":
            return await self.feedback(ctx, essay_id, locale)
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        text = excerpt.strip() if mode == "partial" else essay.body
        if not text.strip():
            raise CharLimitError(params={"field": "body", "limit": 1, "count": 0})
        lines = self._brief(essay) + [
            f"Review mode: {mode}",
            f"Word count: {essay.word_count}",
            f"Draft: {text[:_BODY_TO_MODEL]}",
        ]
        data = await self._ask(ctx, "sentences", locale, lines)
        notes = []
        for raw in (data.get("sentences") or [])[: prompt.MAX_SENTENCES]:
            quote, comment = _line(_get(raw, "quote")), _line(_get(raw, "comment"))
            if quote and comment:
                notes.append(SentenceNote(quote[:80], comment))
        return Feedback(
            _line(data.get("summary")),
            _lines(data.get("strengths"), prompt.MAX_POINTS),
            _lines(data.get("suggestions"), prompt.MAX_POINTS),
            essay.word_count,
            essay.word_limit,
            notes,
        )

    async def refine(
        self, ctx: AdmissionContext, essay_id: UUID, locale: str, action: str, text: str
    ) -> list[str]:
        """Hints for rewording, connecting or merging a passage; never new text."""
        await self._gate(ctx)
        async with self._uow() as uow:
            essay = await self._essay(uow, ctx, essay_id)
        data = await self._ask(
            ctx,
            "refine",
            locale,
            self._brief(essay) + [f"Action: {action}", f"Passage: {text[:2000]}"],
        )
        return _lines(data.get("hints"), prompt.MAX_HINTS)

    async def life_story(
        self, ctx: AdmissionContext, text: str, locale: str
    ) -> LifeStoryReading:
        """Read a free life story: drivers, fields to support, topics to leave out."""
        await self._gate(ctx)
        async with self._uow() as uow:
            lines = await self._context(uow, ctx)
        data = await self._ask(
            ctx, "life_story", locale, [*lines, f"Story: {text[:_BODY_TO_MODEL]}"]
        )
        cap = prompt.MAX_POINTS
        return LifeStoryReading(
            _lines(data.get("drivers"), cap),
            _lines(data.get("support"), cap),
            _lines(data.get("leave_out"), cap),
            _lines(data.get("ideas"), prompt.MAX_HINTS),
        )


class UowEssayReader:
    """`EssayReader` over the unit of work."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the transaction factory."""
        self._uow = uow_factory

    async def latest_for(
        self, student_id: UUID, *, shared_only: bool = False
    ) -> list[EssayText]:
        """Return live drafts, or the newest shared version of each essay."""
        out: list[EssayText] = []
        async with self._uow() as uow:
            for essay in await uow.essays.list_for(student_id):
                body, at = essay.body, essay.updated_at
                if shared_only:
                    shared = _first_shared(await uow.essays.versions(essay.id))
                    if shared is None:
                        continue
                    body, at = shared.body, shared.created_at
                if not body.strip() or at is None:
                    continue
                out.append(
                    EssayText(
                        essay_id=essay.id,
                        student_id=essay.student_id,
                        kind=essay.kind,
                        title=essay.title,
                        prompt_text=essay.prompt_text,
                        word_limit=essay.word_limit,
                        list_entry_id=essay.list_entry_id,
                        body=body,
                        word_count=word_count(body),
                        updated_at=at,
                    )
                )
        return out


def _first_shared(versions: Sequence[EssayVersion]) -> EssayVersion | None:
    return next((v for v in versions if v.shared), None)
