"""Profile setup: validated answers, conditional visibility, save and resume."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.checklist import ensure_all
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidAnswerError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.profile import AdmissionProfile
from app.modules.admission.domain.questions import (
    BY_ID,
    QUESTION_SET_VERSION,
    QUESTIONS,
    Question,
)
from app.modules.admission.domain.runtime_settings import WELLBEING_QUESTIONS
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class ProfileView:
    """The answers a reader may see, plus where the student should resume."""

    student_id: UUID
    account_kind: str
    stage: str
    question_set_version: str
    answers: dict[str, Any]
    next_question: str | None
    missing_required: tuple[str, ...]
    setup_completed: bool
    lock_version: int
    family_budget: str | None = None
    budget_shared: bool = False


def active_questions(*, alumni: bool, wellbeing: bool) -> tuple[Question, ...]:
    """Return the questions this student answers: conditions and flags applied."""
    return tuple(
        q
        for q in QUESTIONS
        if (q.enabled or (wellbeing and q.sensitivity == "wellbeing"))
        and (q.visible_if is None or (alumni and q.visible_if.endswith("alumni")))
    )


def _bad(q: Question) -> InvalidAnswerError:
    return InvalidAnswerError(params={"question": q.id})


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _strings(q: Question, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad(q)
    if q.max_choices is not None and len(value) > q.max_choices:
        raise _bad(q)
    if len(set(value)) != len(value):
        raise _bad(q)
    return value


def _check_choice(q: Question, value: Any) -> None:
    if not isinstance(value, str) or (q.options and value not in q.options):
        raise _bad(q)


def _check_multi(q: Question, value: Any) -> None:
    picked = _strings(q, value)
    if q.options and not set(picked) <= set(q.options):
        raise _bad(q)


def _check_range(q: Question, value: Any) -> None:
    if not (
        isinstance(value, list)
        and len(value) == 2
        and all(_is_number(v) for v in value)
        and value[0] <= value[1]
    ):
        raise _bad(q)


def _check_date(q: Question, value: Any) -> None:
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise _bad(q) from None


def _check_repeat(q: Question, value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str | dict) for v in value):
        raise _bad(q)


def _check_text(q: Question, value: Any) -> None:
    if not isinstance(value, str):
        raise _bad(q)


def _check_number(q: Question, value: Any) -> None:
    if not _is_number(value):
        raise _bad(q)


def _check_switch(q: Question, value: Any) -> None:
    if not isinstance(value, bool):
        raise _bad(q)


_CHECKS: dict[str, Callable[[Question, Any], None]] = {
    "single": _check_choice,
    "multi": _check_multi,
    "country": _strings,  # type: ignore[dict-item]
    "combobox": _strings,  # type: ignore[dict-item]
    "text": _check_text,
    "number": _check_number,
    "money": _check_number,
    "scale": _check_number,
    "range": _check_range,
    "date": _check_date,
    "switch": _check_switch,
    "repeat": _check_repeat,
}


def validate_answer(q: Question, value: Any) -> Any:
    """Return the cleaned answer of a question or raise `invalid_answer`."""
    if q.kind == "locked":
        raise AdmissionForbiddenError(params={"permission": "profile:locked"})
    check = _check_choice if q.kind == "money" and q.options else _CHECKS.get(q.kind)
    if check is not None:
        check(q, value)
    return value


def _answered(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _can_see(q: Question, permissions: frozenset[Permission], owner: bool) -> bool:
    if owner or q.visible_to == "mentor":
        return True
    if q.visible_to == "finance_read":
        return Permission.FINANCE_READ in permissions
    if q.visible_to == "staff":
        return Permission.NOTES_STAFF in permissions
    return False


BUDGET_QUESTION = "q32"
"""The family budget band of the profile (finance-sensitive)."""


def _view(
    profile: AdmissionProfile,
    questions: tuple[Question, ...],
    permissions: frozenset[Permission],
    owner: bool,
    limited: bool = False,
    budget_shared: bool = False,
) -> ProfileView:
    answers = profile.answers
    missing = tuple(
        q.id for q in questions if q.required and not _answered(answers.get(q.id))
    )
    first = next((q.id for q in questions if not _answered(answers.get(q.id))), None)
    budget = answers.get(BUDGET_QUESTION)
    return ProfileView(
        family_budget=(
            budget if (owner or budget_shared) and isinstance(budget, str) else None
        ),
        budget_shared=budget_shared,
        student_id=profile.student_id,
        account_kind=profile.account_kind,
        stage=profile.stage,
        question_set_version=profile.question_set_version,
        answers={
            k: v
            for k, v in answers.items()
            if not limited and k in BY_ID and _can_see(BY_ID[k], permissions, owner)
        },
        next_question=first,
        missing_required=missing,
        setup_completed=profile.setup_completed_at is not None,
        lock_version=profile.lock_version,
    )


class ProfileService:
    """Read and save the background answers."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        runtime: RuntimeSettingsService,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._runtime = runtime
        self._clock = clock

    async def _questions(self, alumni: bool) -> tuple[Question, ...]:
        flag = (await self._runtime.get()).get(WELLBEING_QUESTIONS, False)
        return active_questions(alumni=alumni, wellbeing=flag is True)

    async def _budget_shared(
        self, ctx: AdmissionContext, student_id: UUID, owner: bool
    ) -> bool:
        """The budget is shown to the owner and to counselors once it is shared."""
        if not owner and Role.COUNSELOR not in ctx.actor.roles:
            return False
        return await self._access.finance_shared(student_id)

    async def get(self, ctx: AdmissionContext, student_id: UUID) -> ProfileView:
        """Return the answers visible to the caller; a new student gets an empty one."""
        res = await self._access.require(
            ctx, student_id, Permission.PROFILE_READ, object_type="profile"
        )
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
        if profile is None:
            if not res.owner:
                raise AdmissionNotFoundError()
            profile = AdmissionProfile(student_id=student_id)
        return _view(
            profile,
            await self._questions(profile.account_kind == "alumni"),
            res.permissions,
            res.owner,
            limited=res.limited,
            budget_shared=await self._budget_shared(ctx, student_id, res.owner),
        )

    @staticmethod
    def _apply(
        profile: AdmissionProfile,
        questions: tuple[Question, ...],
        answers: dict[str, Any],
    ) -> None:
        """Validate the answers against the questions and store them."""
        visible = {q.id: q for q in questions}
        for qid, value in answers.items():
            q = visible.get(qid)
            if q is None:
                raise AdmissionNotFoundError(params={"question": qid})
            value = validate_answer(q, value) if _answered(value) else None
            if value is None:
                profile.answers.pop(qid, None)
            elif q.enabled:
                profile.set_answer(qid, value)
            else:
                profile.answers[qid] = value

    def _advance(self, profile: AdmissionProfile, done: bool) -> None:
        """Move the stage and the completion stamp with the required answers."""
        if done and profile.setup_completed_at is None:
            profile.setup_completed_at = self._clock.now()
            if profile.stage == "setup":
                profile.stage = "words"
        elif not done:
            profile.setup_completed_at = None
            if profile.stage == "words":
                profile.stage = "setup"

    async def save(
        self,
        ctx: AdmissionContext,
        answers: dict[str, Any],
        lock_version: int | None,
    ) -> ProfileView:
        """Save answers (one or many); a stale `lock_version` raises a conflict.

        An existing profile needs the `lock_version` it was read with.
        """
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "profile:edit"})
        async with self._uow() as uow:
            stored = await uow.profiles.get(ctx.user_id)
            if stored is not None and stored.lock_version != lock_version:
                raise AdmissionConflictError()
            profile = stored or AdmissionProfile(student_id=ctx.user_id)
            questions = await self._questions(profile.account_kind == "alumni")
            self._apply(profile, questions, answers)
            done = all(
                _answered(profile.answers.get(q.id)) for q in questions if q.required
            )
            self._advance(profile, done)
            if done:
                await ensure_all(uow, ctx.user_id)
            profile.question_set_version = QUESTION_SET_VERSION
            saved = await uow.profiles.save(
                profile, None if stored is None else stored.lock_version
            )
            await uow.commit()
        return _view(saved, questions, res.permissions, True)
