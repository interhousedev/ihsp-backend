"""College readiness: one percentage and its parts, from what the student has done.

Weights come from `AdmissionSettings.readiness`; an administrator overrides them
in `admission.runtime_settings` (key `readiness_weights`).
"""

import math
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    can_edit_settings,
)
from app.modules.admission.application.list_plan import ListPlanService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.study_focus import load_study_focus
from app.modules.admission.domain.calendar import TASHKENT
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ReadinessWeightsError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.runtime_settings import READINESS_WEIGHTS
from app.modules.admission.ports.unit_of_work import UowFactory
from app.settings_admission import ReadinessSettings
from app.shared.clock import Clock

COMPONENTS: Final = (
    "major",
    "plans",
    "countries",
    "list",
    "essays",
    "activities",
    "tests",
    "documents",
    "tasks",
)
NEXT_ACTIONS: Final[dict[str, tuple[str, str]]] = {
    "major": ("choose_major", "/career/"),
    "plans": ("add_plans", "/plan/"),
    "countries": ("choose_countries", "/chooser/search/?prefs=1"),
    "list": ("balance_list", "/chooser/list/"),
    "essays": ("write_essay", "/essays"),
    "activities": ("ready_activities", "/activities"),
    "tests": ("add_test_score", "/tests"),
    "documents": ("upload_documents", "/documents"),
    "tasks": ("clear_tasks", "/tasks"),
}
COUNTRIES_QUESTION: Final = "q24"
LABELS: Final = ("reach", "target", "safety")
"""Dream (reach), target and safety: the kinds a balanced list holds."""


def _filled(value: object) -> bool:
    return value not in (None, "", [], {})


@dataclass(frozen=True, slots=True)
class ReadinessComponent:
    """One part of the score; `next_action` is None when it is complete."""

    key: str
    score: int
    weight: float
    next_action: str | None
    url_path: str | None


@dataclass(frozen=True, slots=True)
class Readiness:
    """The overall percentage and its parts."""

    percent: int
    components: tuple[ReadinessComponent, ...]


def ratio_score(done: float, total: float) -> int:
    """Return `done / total` as 0-100, clamped; an empty total is 0."""
    if total <= 0:
        return 0
    return round(max(0.0, min(1.0, done / total)) * 100)


def effective_weights(defaults: ReadinessSettings, stored: object) -> dict[str, float]:
    """Merge stored weights over the defaults; bad or all-zero input is ignored."""
    weights = {k: float(defaults.weights.get(k, 0)) for k in COMPONENTS}
    if isinstance(stored, dict):
        merged = dict(weights)
        for key, value in stored.items():
            if (
                key in merged
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
            ):
                merged[key] = float(value)
        if sum(merged.values()) > 0:
            weights = merged
    return weights


def _valid_weight(weight: float) -> bool:
    return math.isfinite(weight) and 0 <= weight <= 1000


def combine(scores: dict[str, int | None], weights: dict[str, float]) -> Readiness:
    """Weighted mean of the applicable parts.

    A part scored `None` has nothing applicable (no tasks, no documents needed):
    it is left out of the list and of the mean, not counted as 0.
    """
    parts = []
    for key in COMPONENTS:
        score = scores.get(key)
        if score is None:
            continue
        action = NEXT_ACTIONS[key] if score < 100 else (None, None)
        parts.append(ReadinessComponent(key, score, weights[key], *action))
    total = sum(p.weight for p in parts)
    percent = round(sum(p.score * p.weight for p in parts) / total) if total > 0 else 0
    return Readiness(percent, tuple(parts))


class ReadinessService:
    """Computes the readiness of a student the caller may read."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        runtime: RuntimeSettingsService,
        settings: ReadinessSettings,
        clock: Clock,
        list_plan: ListPlanService,
    ) -> None:
        """Keep the collaborators."""
        self._list_plan = list_plan
        self._uow = uow_factory
        self._access = access
        self._runtime = runtime
        self._settings = settings
        self._clock = clock

    async def get(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> Readiness:
        """Readiness of the caller or, with PROFILE_READ, of a student in scope."""
        target = student_id or ctx.user_id
        await self._access.require(
            ctx, target, Permission.PROFILE_READ, object_type="readiness"
        )
        today = self._clock.now().astimezone(TASHKENT).date()
        cfg = self._settings
        weights = effective_weights(
            cfg, (await self._runtime.get()).get(READINESS_WEIGHTS)
        )
        async with self._uow() as uow:
            profile = await uow.profiles.get(target)
            goals = await uow.goals.list_for(target)
            items = await uow.items.list_for(target)
            essays = await uow.essays.list_for(target)
            entries = await uow.test_scores.entries(target)
            checklist = await uow.checklist.for_student(target)
            shortlist = await uow.shortlist.entries(target)
            tasks = await uow.tasks.list_for(target)
            focus = await load_study_focus(uow, target)
        answers = profile.answers if profile is not None else {}
        scores: dict[str, int | None] = {}
        scores["major"] = 100 if focus.chosen else 0
        planned = sum(1 for g in goals if g.status != "dropped")
        scores["plans"] = ratio_score(planned, max(cfg.plans_target, 1))
        scores["countries"] = 100 if _filled(answers.get(COUNTRIES_QUESTION)) else 0
        scores["list"] = await self._list_score(ctx, target, len(shortlist))
        points = sum(1.0 if e.status == "final" else 0.5 for e in essays)
        scores["essays"] = ratio_score(points, max(cfg.essays_target, 1))
        ready = sum(1 for i in items if i.status == "ready")
        scores["activities"] = ratio_score(ready, max(cfg.activities_target, 1))
        received = {e.test_id for e in entries if e.status == "score_received"}
        scores["tests"] = ratio_score(len(received), max(cfg.tests_target, 1))
        applicable = [c for c in checklist if c.status != "n_a"]
        scores["documents"] = (
            ratio_score(
                sum(1 for c in applicable if c.status == "done"), len(applicable)
            )
            if applicable
            else None
        )
        overdue = sum(1 for t in tasks if t.is_overdue(today))
        done = sum(1 for t in tasks if t.status == "done")
        scores["tasks"] = ratio_score(done - overdue, len(tasks)) if tasks else None
        return combine(scores, weights)

    async def _list_score(
        self, ctx: AdmissionContext, student_id: UUID, size: int
    ) -> int:
        """Half the list's length against the target, half its spread of kinds."""
        counts = dict.fromkeys(LABELS, 0)
        try:
            insights = await self._list_plan.insights(ctx, student_id)
            counts = {k: getattr(insights.balance, k) for k in LABELS}
        except (AdmissionForbiddenError, AdmissionNotFoundError):
            pass  # the viewer may not read labels: score the length alone
        length = ratio_score(size, max(self._settings.list_target, 1))
        if not any(counts.values()):
            return length if size == 0 else round(length / 2)
        kinds = ratio_score(sum(1 for v in counts.values() if v), len(LABELS))
        return round((length + kinds) / 2)

    def _require_admin(self, ctx: AdmissionContext) -> None:
        if not can_edit_settings(ctx, self._clock.now()):
            raise AdmissionForbiddenError(params={"permission": "settings:edit"})

    async def weights(self, ctx: AdmissionContext) -> dict[str, float]:
        """The weights in force (any admission staff member)."""
        if not ctx.admission.is_staff:
            raise AdmissionForbiddenError(params={"permission": "settings:read"})
        stored = (await self._runtime.get()).get(READINESS_WEIGHTS)
        return effective_weights(self._settings, stored)

    async def set_weights(
        self, ctx: AdmissionContext, weights: dict[str, float]
    ) -> dict[str, float]:
        """Store new weights; every part is required, none negative, one above 0."""
        self._require_admin(ctx)
        if (
            set(weights) != set(COMPONENTS)
            or any(not _valid_weight(w) for w in weights.values())
            or sum(weights.values()) <= 0
        ):
            raise ReadinessWeightsError()
        async with self._uow() as uow:
            await uow.runtime_settings.save(
                READINESS_WEIGHTS, {k: weights[k] for k in COMPONENTS}, ctx.user_id
            )
            await uow.commit()
        self._runtime.invalidate()
        return await self.weights(ctx)
