"""Shared steps of the exam use cases: load a sitting, close it, present it."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningAttemptQuestionView,
    LearningExamModuleRefView,
    LearningExamModuleReviewView,
    LearningExamModuleRunView,
    LearningExamResultView,
    LearningExamSectionScoreView,
    LearningExamSessionView,
    LearningReviewItemView,
)
from app.modules.lms.domain.learning.block_results import result_key
from app.modules.lms.domain.learning.errors import ExamNotFoundError, NotEnrolledError
from app.modules.lms.domain.learning.exam import (
    ExamSitting,
    ModuleRun,
    as_test,
    close_expired,
    exam_max_points,
    find_module,
    module_review,
    next_module,
    pct,
    section_scores,
    session_key,
    variant_of,
)
from app.modules.lms.domain.step_content import ExamBlock, ExamModule, ExamSection
from app.modules.lms.domain.student_render import render_questions
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock

T = TypeVar("T")


@dataclass(slots=True)
class ExamContext:
    """A loaded sitting (None before the first module) and its pinned exam."""

    user_id: UUID
    step_id: UUID
    block: ExamBlock
    sitting: ExamSitting | None
    preview: bool = False

    @property
    def key(self) -> str:
        """The state card of the sitting; staff previews keep a separate one."""
        base = session_key(self.block.id)
        return f"preview-{base}" if self.preview else base


class ExamUseCase:
    """Base of the exam use cases: one transaction around a loaded sitting."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        completion: StepCompletion,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.completion = completion
        self.gate = gate

    async def run(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        change: Callable[[ExamContext, datetime], T],
    ) -> tuple[LearningExamSessionView, T]:
        """Load, close an expired module, apply ``change``, store and present.

        A sitting is pinned to the revision it began on; a new sitting starts on
        the live revision. Access rules gate the step as for any block, and the
        learner must be enrolled. Course staff who are not enrolled take an
        unscored preview sitting: it is stored apart and never writes a result,
        points or completion.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            preview = False
            try:
                context = await require_enrolled(uow, actor, step_id, self.gate)
            except NotEnrolledError:
                context = await load_live_step(uow, step_id)
                if not (await staff_access(uow, actor, context.course.id)).is_staff:
                    raise
                preview = True
            state = await uow.states.get(actor.user_id, step_id)
            prefix = "preview-" if preview else ""
            raw = (state.cards if state else {}).get(prefix + session_key(block_id))
            sitting = ExamSitting.from_json(raw) if raw else None
            revision_id = (
                UUID(sitting.revision_id) if sitting else context.live_step.revision_id
            )
            block = _find_exam(
                (await load_revision(uow, revision_id)).content.blocks, block_id
            )
            exam = ExamContext(actor.user_id, step_id, block, sitting, preview)
            before = _fingerprint(sitting)
            if sitting is not None:
                close_expired(block, sitting, now)
            outcome = change(exam, now)
            if exam.sitting is not None and not exam.sitting.revision_id:
                exam.sitting.revision_id = str(revision_id)
            changed = before != _fingerprint(exam.sitting)
            await self._settle(uow, exam, now, changed=changed)
            await uow.commit()
        return session_view(exam, now), outcome

    async def _settle(
        self,
        uow: LearningUnitOfWork,
        exam: ExamContext,
        now: datetime,
        *,
        changed: bool,
    ) -> None:
        """Finish a sitting with no module left; store it when it changed."""
        sitting = exam.sitting
        if sitting is None:
            return
        if (
            sitting.finished_at is None
            and sitting.current is None
            and sitting.runs
            and next_module(exam.block, sitting.runs) is None
        ):
            sitting.finished_at = now
            changed = True
        if sitting.finished_at == now and not exam.preview:
            await uow.states.save_card(
                exam.user_id,
                exam.step_id,
                result_key(exam.block.id),
                _result_record(exam.block, sitting),
                now=now,
            )
        if not changed:
            return
        await uow.states.save_card(
            exam.user_id,
            exam.step_id,
            exam.key,
            sitting.to_json(),
            now=now,
        )
        if sitting.finished_at == now and not exam.preview:
            await self.completion.after_block_result(
                uow, exam.user_id, exam.step_id, now
            )


def _find_exam(blocks: list[Any], block_id: str) -> ExamBlock:
    """Return the exam block with this id or raise ExamNotFoundError."""
    for block in blocks:
        if isinstance(block, ExamBlock) and block.id == block_id:
            return block
    raise ExamNotFoundError(params={"block_id": block_id})


def _fingerprint(sitting: ExamSitting | None) -> object:
    """Return a comparable snapshot of a sitting."""
    return None if sitting is None else sitting.to_json()


def _result_record(block: ExamBlock, sitting: ExamSitting) -> dict[str, Any]:
    """Return the stored block result of a finished sitting (points and progress)."""
    score = sum((run.score for run in sitting.runs), Decimal(0))
    top = sum((run.max_score for run in sitting.runs), Decimal(0))
    scaled = [s.scaled for s in section_scores(block, sitting) if s.scaled is not None]
    return {
        "kind": "exam",
        "score": float(score),
        "max_score": float(top),
        "pct": float(pct(score, top)),
        "scaled_total": sum(scaled) if scaled else None,
        "completed": True,
        "passed": True,
        "max_points": float(exam_max_points(block)),
    }


# - - - Presenting - - -


def session_view(exam: ExamContext, now: datetime) -> LearningExamSessionView:
    """Return the sitting as its owner may see it now.

    Questions are included only for the open module; correct answers only in
    the result of a finished sitting.
    """
    block, sitting = exam.block, exam.sitting
    runs = sitting.runs if sitting else []
    done = sum(1 for run in runs if not run.is_open)
    if sitting is not None and sitting.finished_at is not None:
        return LearningExamSessionView(
            block_id=block.id,
            status="finished",
            server_now=now,
            modules_done=done,
            result=_result(block, sitting, sitting.finished_at),
        )
    current = sitting.current if sitting else None
    if current is not None:
        section, module = find_module(block, current.module_id)
        return LearningExamSessionView(
            block_id=block.id,
            status="in_module",
            server_now=now,
            modules_done=done,
            current=_run_view(block, section, module, current),
        )
    following = next_module(block, runs)
    last_section = runs[-1].section_id if runs else None
    return LearningExamSessionView(
        block_id=block.id,
        status="between" if runs else "not_started",
        server_now=now,
        modules_done=done,
        next=_ref(block, *following) if following else None,
        next_is_new_section=following is not None
        and last_section is not None
        and following[0].id != last_section,
    )


def _ref_fields(
    block: ExamBlock, section: ExamSection, module: ExamModule
) -> dict[str, Any]:
    """Return the fields that place a module in the exam."""
    section_no = next(i for i, s in enumerate(block.sections, 1) if s.id == section.id)
    position = next(i for i, m in enumerate(section.modules, 1) if m.id == module.id)
    adaptive_second = section.adaptive and len(section.modules) == 3 and position == 3
    return {
        "section_id": section.id,
        "module_id": module.id,
        "section_title": section.title,
        "module_title": module.title,
        "section_no": section_no,
        "module_no": 2 if adaptive_second else position,
        "time_limit_sec": module.time_limit_sec,
        "questions_count": len(module.questions),
    }


def _ref(
    block: ExamBlock, section: ExamSection, module: ExamModule
) -> LearningExamModuleRefView:
    """Return where a module sits in the exam."""
    return LearningExamModuleRefView(**_ref_fields(block, section, module))


def _questions(module: ExamModule) -> list[LearningAttemptQuestionView]:
    """Return the questions of a module without correctness data."""
    return [
        LearningAttemptQuestionView(**question)
        for question in render_questions(
            as_test(module), list(variant_of(module).question_ids), {}
        )
    ]


def _run_view(
    block: ExamBlock, section: ExamSection, module: ExamModule, run: ModuleRun
) -> LearningExamModuleRunView:
    """Return the open module with its questions and saved answers."""
    return LearningExamModuleRunView(
        **_ref_fields(block, section, module),
        started_at=run.started_at,
        deadline_at=run.deadline_at,
        questions=_questions(module),
        answers=run.answers,
    )


def _result(
    block: ExamBlock, sitting: ExamSitting, finished_at: datetime
) -> LearningExamResultView:
    """Return the scores of a finished sitting with the review of every module."""
    sections = section_scores(block, sitting)
    titles = {section.id: section.title for section in block.sections}
    scaled = [s.scaled for s in sections if s.scaled is not None]
    modules: list[LearningExamModuleReviewView] = []
    for run in sitting.runs:
        section, module = find_module(block, run.module_id)
        modules.append(
            LearningExamModuleReviewView(
                **_ref_fields(block, section, module),
                late=run.late,
                score=float(run.score),
                max_score=float(run.max_score),
                questions=_questions(module),
                answers=run.answers,
                review=[
                    LearningReviewItemView(**item)
                    for item in module_review(module, run)
                ],
            )
        )
    scaling = block.scaling
    return LearningExamResultView(
        finished_at=finished_at,
        score=float(sum((s.score for s in sections), Decimal(0))),
        max_score=float(sum((s.max_score for s in sections), Decimal(0))),
        scaled_total=sum(scaled) if scaled else None,
        scaled_min=scaling.min_score * len(sections) if scaling else None,
        scaled_max=scaling.max_score * len(sections) if scaling else None,
        sections=[
            LearningExamSectionScoreView(
                section_id=s.section_id,
                title=titles.get(s.section_id, ""),
                score=float(s.score),
                max_score=float(s.max_score),
                scaled_score=s.scaled,
            )
            for s in sections
        ],
        modules=modules,
    )
