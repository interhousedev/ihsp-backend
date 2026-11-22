"""The full application review: seven section agents and one lead agent.

`start` checks the owner, the `admission_ai` consent, the AI access and the weekly
soft limit, stores a queued version and kicks the job. `run` (the job) fans out
the section agents in parallel; a failed section is recorded and the rest go on.
The lead merges the successful sections; when it fails the report is merged
deterministically from the sections. Student text reaches a model only inside
`<student_text>` delimiters and every model text is cleaned before it is stored.
"""

import asyncio
import logging
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.app_review import AppReview
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.infrastructure.ai.prompts import app_review as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.app_review import (
    AppReviewRepository,
    ReviewInputs,
    ReviewInputsLoader,
)
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.shared.ai_access import scope_of
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock
from app.shared.contracts.ai import AiAccessRevokedError
from app.shared.ids import new_id
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker
from app.shared.usage_context import bind_usage_user, reset_usage_actor

log = logging.getLogger(__name__)

TASK_NAME: Final = "admission.app_review"
_WEEK: Final = 7 * 24 * 3600
_LOCALES: Final = frozenset({"uz", "ru", "en"})
_STAFF_NEEDS: Final = frozenset(
    {
        Permission.PROFILE_READ,
        Permission.WORDS_READ,
        Permission.ACTIVITIES_READ,
        Permission.LIST_READ,
        Permission.ESSAYS_READ,
        Permission.DOCUMENTS_READ,
        Permission.NOTES_STAFF,
    }
)


def _clean(text: Any, limit: int = prompt.TEXT_MAX) -> str:
    return nfc(plain(str(text)))[:limit]


def _refs(values: Any, known: frozenset[str]) -> list[str]:
    return [str(v) for v in (values or []) if str(v) in known][:6]


_ID_PREFIX: Final = {
    "essay": "essay:",
    "list_entry": "entry:",
    "activities": "item:",
    "honors": "item:",
    "survey": "answer:",
    "grades": "course:",
}
_SCREEN_KINDS: Final = frozenset(prompt.LINK_KINDS) - {"none"}
_VERDICTS: Final = frozenset({"strong", "mixed", "weak", "missing"})


def clean_link(kind: str, ref: str, known: frozenset[str]) -> dict[str, str]:
    """A link to a screen; a ref that was not in the input becomes kind none."""
    ref = ref.strip()
    if kind not in _SCREEN_KINDS:
        return {"kind": "none", "ref": ""}
    if not ref:
        return {"kind": kind, "ref": ""}
    prefix = _ID_PREFIX.get(kind)
    if prefix is None or f"{prefix}{ref}" not in known:
        return {"kind": "none", "ref": ""}
    return {"kind": kind, "ref": ref}


def section_view(out: prompt.SectionReport, known: frozenset[str]) -> dict[str, Any]:
    """The cleaned findings, subsections and AO view of one section report."""
    kept = [i for i, f in enumerate(out.findings) if f.text.strip()]
    position = {orig: new for new, orig in enumerate(kept)}
    findings = [
        {
            "kind": f.kind,
            "text": _clean(f.text),
            "evidence": _refs(f.evidence, known),
            "link": clean_link(f.link.kind, f.link.ref, known),
        }
        for f in out.findings
        if f.text.strip()
    ]
    subsections = [
        {
            "key": _clean(s.key, 40),
            "title": _clean(s.title, 120),
            "verdict": s.verdict if s.verdict in _VERDICTS else "mixed",
            "ao_view": _clean(s.ao_view, prompt.VIEW_MAX),
            "finding_indexes": sorted(
                {position[i] for i in s.finding_indexes if i in position}
            ),
            "link": clean_link(s.link.kind, s.link.ref, known),
        }
        for s in out.subsections
        if s.title.strip()
    ]
    return {
        "ao_view": _clean(out.ao_view, prompt.VIEW_MAX),
        "subsections": subsections,
        "findings": findings,
    }


def section_lines(key: str, data: ReviewInputs) -> list[tuple[str, str]]:
    """The data one section agent reads; empty means the section is skipped."""
    words = [("words", "Profile words: " + ", ".join(data.words))] if data.words else []
    match key:
        case "profile":
            return data.profile
        case "activities":
            return data.items
        case "alignment":
            return words + data.items + data.essays if words else []
        case "essays":
            return data.essays
        case "academics":
            return data.courses
        case "universities":
            return data.universities + data.profile
        case _:
            return data.readiness


class AppReviewService:
    """Starts, runs and reads the full application reviews."""

    def __init__(
        self,
        repo: AppReviewRepository,
        inputs: ReviewInputsLoader,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        limiter: RateLimiter,
        quota: QuotaOf,
        prompts: PromptSource,
        kicker: TaskKicker,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._repo = repo
        self._inputs = inputs
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._limiter = limiter
        self._quota = quota
        self._prompts = prompts
        self._kicker = kicker
        self._limits = limits

    async def _system(self, task: AiTask, locale: str) -> str:
        """The task's system prompt followed by the editable rules slot."""
        lead = AiTask.ADMIT_APP_REVIEW_LEAD
        return prompt.with_rules(
            await self._prompts.text(task, "system", locale),
            await self._prompts.text(lead, "rules", locale),
        )

    async def _has_consent(self, student_id: UUID) -> bool:
        granted = (await self._consents.granted([student_id])).get(
            student_id, frozenset()
        )
        return AI in granted

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "app_review"})

    async def start(self, ctx: AdmissionContext, locale: str) -> AppReview:
        """Queue a new review version of the caller's application."""
        await self._owner(ctx)
        uid = ctx.user_id
        if not await self._has_consent(uid):
            raise ConsentRequiredError(params={"purpose": AI})
        scope = scope_of(AiTask.ADMIT_APP_REVIEW_LEAD.value)
        if self._limits and (await self._limits.ai_access(uid)).blocks(scope):
            raise AiAccessRevokedError(params={"scope": scope})
        now = self._clock.now()
        if any(r.blocks_new(now) for r in await self._repo.list_for(uid, limit=3)):
            raise AdmissionConflictError(params={"reason": "review_in_progress"})
        limit = await self._quota(uid)
        if limit is not None:
            await self._limiter.hit(
                f"admission:app_review:{uid}", limit=limit, window_seconds=_WEEK
            )
        review = await self._repo.add(
            AppReview(
                id=new_id(),
                student_id=uid,
                version=0,
                status="queued",
                locale=locale if locale in _LOCALES else "en",
                created_by=uid,
                created_at=now,
            )
        )
        try:
            await self._kicker.kick(TASK_NAME, review_id=str(review.id))
        except Exception:
            review.status = "failed"
            review.error_code = "kick_failed"
            review.finished_at = self._clock.now()
            await self._repo.save(review)
            raise
        return review

    async def list_mine(self, ctx: AdmissionContext) -> list[AppReview]:
        """The caller's review versions, newest first."""
        await self._owner(ctx)
        return await self._repo.list_for(ctx.user_id)

    async def get_mine(self, ctx: AdmissionContext, review_id: UUID) -> AppReview:
        """One of the caller's reviews."""
        await self._owner(ctx)
        review = await self._repo.get(review_id)
        if review is None or review.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return review

    async def _staff(self, ctx: AdmissionContext, student_id: UUID) -> None:
        res = await self._access.require(
            ctx, student_id, Permission.DOCUMENTS_READ, object_type="app_review"
        )
        if res.limited or not _STAFF_NEEDS <= res.permissions:
            raise AdmissionForbiddenError(params={"permission": "app_review"})

    async def staff_list(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[AppReview]:
        """A counselor's view: the versions built only from shared material."""
        await self._staff(ctx, student_id)
        return [r for r in await self._repo.list_for(student_id) if r.staff_visible]

    async def staff_get(
        self, ctx: AdmissionContext, student_id: UUID, review_id: UUID
    ) -> AppReview:
        """One staff-visible review of a student in scope."""
        await self._staff(ctx, student_id)
        review = await self._repo.get(review_id)
        if (
            review is None
            or review.student_id != student_id
            or not review.staff_visible
        ):
            raise AdmissionNotFoundError()
        return review

    async def run(self, review_id: UUID) -> None:
        """The job: run the agents and store the result (idempotent per status)."""
        review = await self._repo.get(review_id)
        if review is None or review.status != "queued":
            return
        token = bind_usage_user(review.student_id, unlimited=False)
        try:
            await self._run(review)
        except Exception:
            log.exception("app review %s failed", review_id)
            review.status = "failed"
            review.error_code = review.error_code or "internal"
            review.finished_at = self._clock.now()
            await self._repo.save(review)
        finally:
            reset_usage_actor(token)

    async def _run(self, review: AppReview) -> None:
        review.status = "running"
        review.started_at = self._clock.now()
        await self._repo.save(review)
        if not await self._has_consent(review.student_id):
            review.error_code = "consent_required"
            raise ConsentRequiredError(params={"purpose": AI})
        data = await self._inputs.load(review.student_id)
        review.staff_visible = data.staff_visible
        sections, models, revoked = await self._fan_out(review, data)
        review.sections = sections
        done = [s for s in sections if s["status"] == "done"]
        if not done:
            review.error_code = "ai_access_revoked" if revoked else "sections_failed"
            raise RuntimeError("every section failed")
        known = frozenset(
            ref for s in done for f in s["findings"] for ref in f["evidence"]
        )
        try:
            report, model = await self._lead(sections, known, review.locale)
            models.add(model)
        except Exception as exc:
            log.warning("app review lead failed: %s", type(exc).__name__)
            report = fallback_report(sections)
        review.report = report
        review.models = sorted(models)
        review.status = "done"
        review.finished_at = self._clock.now()
        await self._repo.save(review)

    async def _fan_out(
        self, review: AppReview, data: ReviewInputs
    ) -> tuple[list[dict[str, Any]], set[str], bool]:
        """Run the sections in parallel, saving each one as it finishes."""
        finished: dict[str, dict[str, Any]] = {}
        models: set[str] = set()
        revoked = False
        lock = asyncio.Lock()

        async def one(key: str) -> None:
            nonlocal revoked
            try:
                result = await self._section(key, data, review.locale)
            except Exception as exc:
                revoked = revoked or isinstance(exc, AiAccessRevokedError)
                log.warning("app review section %s failed: %s", key, type(exc).__name__)
                result = {"key": key, "status": "failed"}
            if result.get("model"):
                models.add(result.pop("model"))
            # Serialized, so an older snapshot never lands after a newer one.
            async with lock:
                finished[key] = result
                review.sections = list(finished.values())
                await self._repo.save(review)

        await asyncio.gather(*(one(k) for k in prompt.SECTION_KEYS))
        return [finished[k] for k in prompt.SECTION_KEYS], models, revoked

    async def _section(
        self, key: str, data: ReviewInputs, locale: str
    ) -> dict[str, Any]:
        lines = section_lines(key, data)
        if not lines:
            return {"key": key, "status": "skipped"}
        task = prompt.SECTION_TASKS[key]
        body = [f"Locale: {locale}"] + [f"[{ref}] {text}" for ref, text in lines]
        raw, model = await self._ai.json(
            task=task,
            system=with_brand(await self._system(task, locale)),
            user=delimit(body),
            schema_name=prompt.SECTION_SCHEMA_NAME,
            schema=prompt.SECTION_SCHEMA,
            max_tokens=1500,
        )
        out = prompt.SectionReport.model_validate(raw)
        known = frozenset(ref for ref, _ in lines)
        return {
            "key": key,
            "status": "done",
            "score": out.score,
            "summary": _clean(out.summary),
            **section_view(out, known),
            "next_actions": [_clean(a, 200) for a in out.next_actions if a.strip()],
            "injection_suspected": out.injection_suspected,
            "model": model,
        }

    async def _lead(
        self, sections: list[dict[str, Any]], known: frozenset[str], locale: str
    ) -> tuple[dict[str, Any], str]:
        task = AiTask.ADMIT_APP_REVIEW_LEAD
        body = [f"Locale: {locale}"]
        for s in sections:
            if s["status"] != "done":
                body.append(f"Section {s['key']}: {s['status']}")
                continue
            body.append(f"Section {s['key']} (score {s['score']}): {s['summary']}")
            body += [
                f"- {f['kind']}: {f['text']} [{', '.join(f['evidence'])}]"
                for f in s["findings"]
            ]
            body += [f"- action: {a}" for a in s["next_actions"]]
        raw, model = await self._ai.json(
            task=task,
            system=with_brand(await self._system(task, locale)),
            user=delimit(body),
            schema_name=prompt.LEAD_SCHEMA_NAME,
            schema=prompt.LEAD_SCHEMA,
            max_tokens=3000,
        )
        out = prompt.LeadReview.model_validate(raw)
        by_key = {s["key"]: s for s in sections}
        lead_scores = {s.section: s for s in out.section_scores}
        scores = []
        for key in prompt.SECTION_KEYS:
            sec = by_key[key]
            given = lead_scores.get(key)
            if sec["status"] != "done":
                scores.append({"section": key, "score": 0, "comment": ""})
            elif given is not None:
                scores.append(
                    {
                        "section": key,
                        "score": given.score,
                        "comment": _clean(given.comment),
                    }
                )
            else:
                scores.append(
                    {"section": key, "score": sec["score"], "comment": sec["summary"]}
                )

        def points(items: list[prompt.Point]) -> list[dict[str, Any]]:
            return [
                {
                    "text": _clean(p.text),
                    "section": p.section,
                    "evidence": _refs(p.evidence, known),
                }
                for p in items
                if p.text.strip()
            ]

        report = {
            "headline": _clean(out.headline, 200),
            "overall_score": out.overall_score,
            "strengths": points(out.strengths),
            "risks": points(out.risks),
            "spike": {"score": out.spike.score, "comment": _clean(out.spike.comment)},
            "next_actions": [
                {
                    "title": _clean(a.title, 200),
                    "why": _clean(a.why),
                    "section": a.section,
                    "priority": a.priority,
                }
                for a in sorted(out.next_actions, key=lambda a: a.priority)
                if a.title.strip()
            ],
            "section_scores": scores,
            "injection_suspected": out.injection_suspected
            or any(s.get("injection_suspected") for s in sections),
            "fallback": False,
        }
        return report, model


def fallback_report(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge the sections without the lead model (pure)."""
    done = [s for s in sections if s["status"] == "done"]
    by_key = {s["key"]: s for s in sections}
    align = by_key.get("alignment", {})

    def points(kinds: set[str]) -> list[dict[str, Any]]:
        return [
            {"text": f["text"], "section": s["key"], "evidence": f["evidence"]}
            for s in done
            for f in s["findings"]
            if f["kind"] in kinds
        ][: prompt.MAX_POINTS]

    return {
        "headline": "",
        "overall_score": round(sum(s["score"] for s in done) * 10 / len(done)),
        "strengths": points({"strength"}),
        "risks": points({"risk", "gap"}),
        "spike": {
            "score": align.get("score", 0) if align.get("status") == "done" else 0,
            "comment": align.get("summary", ""),
        },
        "next_actions": [
            {"title": a, "why": "", "section": s["key"], "priority": 2}
            for s in done
            for a in s["next_actions"][:1]
        ][: prompt.MAX_LEAD_ACTIONS],
        "section_scores": [
            {
                "section": key,
                "score": by_key[key].get("score", 0),
                "comment": by_key[key].get("summary", ""),
            }
            for key in prompt.SECTION_KEYS
        ],
        "injection_suspected": any(s.get("injection_suspected") for s in done),
        "fallback": True,
    }
