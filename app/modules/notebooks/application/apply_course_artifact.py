"""Use case: write a Studio output of a course workspace into the course draft.

`preview` is the dry run behind the Apply dialog (what would change, what is wrong);
`apply` does it. The user's click on Apply is the approval, and nothing goes live
before the course is published. All writes go through the LMS use cases, so they
check the `edit` permission, the lock version and the content rules themselves:

- ``course_plan`` creates the sections and steps the draft does not have yet
  (`LmsWorkspaceCommands.apply_outline`, one transaction, nothing is renamed or
  removed).
- ``lesson_draft`` replaces the blocks of a step, or is appended to them
  (`replace_step`), or goes into a new step of a section.
- ``quiz`` and ``flashcards`` are converted to a test block or a flash cards block
  and appended to a step (or put in a new step).

A new step takes two LMS calls, `create_step` and `replace_step`, which are not one
transaction: if the second fails (a content rule the preview should have caught), an
empty step stays in the draft and the error is returned.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.apply_views import (
    APPEND,
    MODES,
    REPLACE,
    ApplyPreviewView,
    ApplyRequest,
    ApplyResultView,
    PlanPreview,
    PlanSectionPreview,
    PlanStepPreview,
    StepPreview,
)
from app.modules.notebooks.application.artifact_engine import require_ready
from app.modules.notebooks.application.course_convert import (
    deck_to_blocks,
    draft_of,
    draft_to_content,
    plan_of,
    plan_to_sections,
    quiz_to_blocks,
)
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    FeatureDisabledError,
    InvalidOptionsError,
    OutputInvalidError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.lms import LmsDraftCommands, LmsQueries, LmsWorkspaceCommands
from app.shared.contracts.lms_blocks import BlockInputError

import structlog

log = structlog.get_logger(__name__)

APPLICABLE = (
    ArtifactKind.COURSE_PLAN,
    ArtifactKind.LESSON_DRAFT,
    ArtifactKind.QUIZ,
    ArtifactKind.FLASHCARDS,
)
KEPT_BY_APPEND = ("test", "flashcards")


@dataclass(frozen=True, slots=True)
class _Output:
    """A ready output of a workspace, with the course it is written into."""

    course_id: UUID
    artifact: Artifact
    content: dict[str, Any]

    @property
    def kind(self) -> ArtifactKind:
        """The kind of the output."""
        return self.artifact.kind

    @property
    def language(self) -> str:
        """The language the output was written in (for the briefs of a plan)."""
        generated = self.content.get("language") or self.artifact.options.get(
            "language"
        )
        return str(generated or "en")


@dataclass(frozen=True, slots=True)
class _StepPlan:
    """The resolved write into one step: the target, the new content, the notes."""

    step_id: UUID | None
    section_id: str | None
    title: str
    lock_version: int | None
    mode: str
    current_blocks: list[dict[str, Any]] | None
    new_blocks: list[dict[str, Any]]
    content: dict[str, Any]
    notes: list[str]


def _problems_of(exc: BlockInputError | InvalidOptionsError) -> list[str]:
    """The messages of a refusal, for the preview."""
    if isinstance(exc, InvalidOptionsError):
        details = exc.params.get("details")
        return [str(item) for item in details] if details else [exc.support_details]
    return [str(exc)]


def _invalid(detail: str) -> InvalidOptionsError:
    """A refusal of the request itself (target, mode)."""
    return InvalidOptionsError(
        params={"details": [detail]}, support_details=detail[:500]
    )


def _blocks_of(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The blocks of a step content as a list of dicts."""
    return [b for b in content.get("blocks") or [] if isinstance(b, dict)]


def _lost_blocks(current: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[str]:
    """Notes about tests and flash cards that a replace would remove."""
    present = {block.get("type") for block in new}
    kinds = sorted({str(b.get("type")) for b in current} & set(KEPT_BY_APPEND))
    return [
        f"The current draft has a {kind} block that the new version does not have; "
        "it is removed. Use append to keep it."
        for kind in kinds
        if kind not in present
    ]


def _plan_preview(result: dict[str, Any]) -> PlanPreview:
    """The dry run of `apply_outline` as a preview."""
    sections: list[PlanSectionPreview] = []
    for raw in result.get("plan") or []:
        steps = [
            PlanStepPreview(
                title=str(step.get("title")),
                step_id=str(step["step_id"]) if step.get("step_id") else None,
                action=str(step.get("action")),
            )
            for step in raw.get("steps") or []
        ]
        sections.append(
            PlanSectionPreview(
                title=str(raw.get("title")),
                section_id=str(raw["section_id"]) if raw.get("section_id") else None,
                action=str(raw.get("action")),
                steps=steps,
            )
        )
    every_step = [step for section in sections for step in section.steps]
    return PlanPreview(
        sections=sections,
        new_sections=sum(1 for s in sections if s.action == "new"),
        new_steps=sum(1 for s in every_step if s.action == "new"),
        existing_steps=sum(1 for s in every_step if s.action != "new"),
    )


class ApplyCourseArtifact:
    """Previews and applies an output of a course workspace to the course draft."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        workspace: LmsWorkspaceCommands | None = None,
        queries: LmsQueries | None = None,
        drafts: LmsDraftCommands | None = None,
    ) -> None:
        """Store the unit of work factory and the LMS ports (None: LMS is off)."""
        self.uow_factory = uow_factory
        self.workspace = workspace
        self.queries = queries
        self.drafts = drafts

    # - - - Public - - -

    async def preview(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        request: ApplyRequest,
    ) -> ApplyPreviewView:
        """Say what `apply` would do, without writing anything.

        Problems that the author can fix (a bad target, an invalid edited plan or
        draft) are returned in ``problems`` with ``can_apply`` false; they are not
        raised.

        Raises:
            NotebookNotFoundError: Not a workspace the actor may use, or no such output.
            InvalidOptionsError: The output is not of an applicable kind.
            ArtifactNotReadyError: The output is not ready.
            FeatureDisabledError: The LMS is not wired.
            ForbiddenError: The actor may not edit the course.
        """
        output = await self._load(actor, notebook_id, artifact_id)
        try:
            if output.kind is ArtifactKind.COURSE_PLAN:
                return await self._preview_plan(actor, output, request)
            plan = await self._step_plan(actor, output, request)
        except (BlockInputError, InvalidOptionsError) as exc:
            return ApplyPreviewView(output.kind.value, False, _problems_of(exc))
        return ApplyPreviewView(
            output.kind.value,
            True,
            notes=plan.notes,
            step=StepPreview(
                step_id=plan.step_id,
                title=plan.title,
                lock_version=plan.lock_version,
                mode=plan.mode,
                current_blocks=plan.current_blocks,
                new_blocks=plan.new_blocks,
            ),
        )

    async def apply(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        request: ApplyRequest,
    ) -> ApplyResultView:
        """Write the output into the course draft.

        Raises:
            NotebookNotFoundError: Not a workspace the actor may use, or no such output.
            InvalidOptionsError: Not an applicable kind, or a bad target or mode.
            ArtifactNotReadyError: The output is not ready.
            OutputInvalidError: The (edited) plan or draft breaks a rule.
            FeatureDisabledError: The LMS is not wired.
            DraftConflictError: The step changed since the preview (stale lock).
            ContentInvalidError: The LMS refused the content.
            ForbiddenError: The actor may not edit the course.
        """
        output = await self._load(actor, notebook_id, artifact_id)
        try:
            if output.kind is ArtifactKind.COURSE_PLAN:
                return await self._apply_plan(actor, output, request)
            return await self._apply_step(actor, output, request)
        except BlockInputError as exc:
            raise OutputInvalidError([str(exc)]) from exc

    # - - - Loading - - -

    async def _load(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> _Output:
        """The ready, applicable output of a workspace the actor may write."""
        self._ports()
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            artifact = await load_artifact(uow, actor.user_id, notebook_id, artifact_id)
        content = require_ready(artifact, *APPLICABLE)
        if not notebook.is_course_workspace or notebook.course_id is None:
            raise _invalid("notebook: only a course workspace can apply an output")
        return _Output(notebook.course_id, artifact, content)

    def _ports(self) -> tuple[LmsWorkspaceCommands, LmsQueries, LmsDraftCommands]:
        """The LMS ports; the feature is off while one of them is missing."""
        if self.workspace is None or self.queries is None or self.drafts is None:
            raise FeatureDisabledError(params={"feature": "lms"})
        return self.workspace, self.queries, self.drafts

    # - - - Course plan - - -

    def _sections(self, output: _Output, request: ApplyRequest) -> list[dict[str, Any]]:
        """The outline to create: the author's edited plan, else the stored one."""
        plan = request.plan or plan_of(output.content)
        return plan_to_sections(plan, output.language)

    async def _preview_plan(
        self, actor: Actor, output: _Output, request: ApplyRequest
    ) -> ApplyPreviewView:
        """A dry run of the outline against the draft."""
        workspace, _, _ = self._ports()
        result = await workspace.apply_outline(
            actor,
            output.course_id,
            self._sections(output, request),
            dry_run=True,
            add_briefs=request.add_briefs,
            via_ai=True,
        )
        return ApplyPreviewView(output.kind.value, True, plan=_plan_preview(result))

    async def _apply_plan(
        self, actor: Actor, output: _Output, request: ApplyRequest
    ) -> ApplyResultView:
        """Create the sections and steps the draft is missing."""
        workspace, _, _ = self._ports()
        result = await workspace.apply_outline(
            actor,
            output.course_id,
            self._sections(output, request),
            dry_run=False,
            add_briefs=request.add_briefs,
            via_ai=True,
        )
        seq = result.get("draft_seq")
        return ApplyResultView(
            kind=output.kind.value,
            created_sections=list(result.get("created_sections") or []),
            created_steps=list(result.get("created_steps") or []),
            draft_seq=seq if isinstance(seq, int) else None,
        )

    # - - - Lesson, quiz, flash cards - - -

    def _material(
        self, output: _Output, request: ApplyRequest
    ) -> tuple[str | None, list[dict[str, Any]], list[str]]:
        """The title (lessons only), the new blocks and the notes about them."""
        if output.kind is ArtifactKind.LESSON_DRAFT:
            draft = request.draft or draft_of(output.content)
            step = draft_to_content(draft)
            made = [str(n) for n in output.content.get("notes") or []]
            return str(step["title"]), list(step["blocks"]), made
        converted = (
            quiz_to_blocks(output.content)
            if output.kind is ArtifactKind.QUIZ
            else deck_to_blocks(output.content)
        )
        return None, converted.blocks, converted.notes

    def _mode(self, output: _Output, request: ApplyRequest) -> str:
        """`append` or `replace`; the default depends on the kind."""
        default = REPLACE if output.kind is ArtifactKind.LESSON_DRAFT else APPEND
        mode = request.mode or default
        if mode not in MODES:
            raise _invalid(f"mode: must be one of {', '.join(MODES)}")
        return mode

    def _target(
        self, output: _Output, request: ApplyRequest
    ) -> tuple[UUID | None, str | None]:
        """``(step id, section id)``: an existing step, or a section for a new one."""
        if request.target_step_id is not None:
            return request.target_step_id, None
        if request.target_section_id:
            return None, request.target_section_id
        planned = output.artifact.options.get("step_id")
        if planned and output.kind is ArtifactKind.LESSON_DRAFT:
            return UUID(str(planned)), None
        raise _invalid("target: choose a step, or a section for a new step")

    async def _step_plan(
        self, actor: Actor, output: _Output, request: ApplyRequest
    ) -> _StepPlan:
        """Resolve the target and build the content to write (nothing is written)."""
        mode = self._mode(output, request)
        step_id, section_id = self._target(output, request)
        title, blocks, notes = self._material(output, request)
        if step_id is None:
            name = title or output.artifact.title
            return _StepPlan(
                step_id=None,
                section_id=section_id,
                title=name,
                lock_version=None,
                mode=mode,
                current_blocks=None,
                new_blocks=blocks,
                content={"title": name, "blocks": blocks},
                notes=notes,
            )
        current = await self._current(actor, output, step_id)
        now = current["content"]
        existing = _blocks_of(now)
        if mode == APPEND:
            name, written = str(now.get("title") or ""), [*existing, *blocks]
        else:
            name, written = title or str(now.get("title") or ""), blocks
            notes = [*notes, *_lost_blocks(existing, blocks)]
        return _StepPlan(
            step_id=step_id,
            section_id=None,
            title=name,
            lock_version=int(current["lock_version"]),
            mode=mode,
            current_blocks=existing,
            new_blocks=blocks,
            content={"title": name, "blocks": written},
            notes=notes,
        )

    async def _current(
        self, actor: Actor, output: _Output, step_id: UUID
    ) -> dict[str, Any]:
        """The draft of the target step; it must belong to this course."""
        _, queries, _ = self._ports()
        current = await queries.step_draft(step_id, actor)
        if str(current.get("course_id")) != str(output.course_id):
            raise _invalid("target_step_id: the step is not in this course")
        return current

    async def _apply_step(
        self, actor: Actor, output: _Output, request: ApplyRequest
    ) -> ApplyResultView:
        """Write the blocks into the step (a new one is created first)."""
        workspace, _, drafts = self._ports()
        plan = await self._step_plan(actor, output, request)
        step_id, lock = plan.step_id, plan.lock_version
        created: list[dict[str, Any]] = []
        if step_id is None or lock is None:
            made = await drafts.create_step(
                actor,
                output.course_id,
                str(plan.section_id),
                plan.title,
                via_mcp=False,
            )
            step_id, lock = UUID(str(made["step_id"])), int(made["lock_version"])
            created.append(
                {
                    "step_id": str(step_id),
                    "section_id": plan.section_id,
                    "title": str(made.get("title") or plan.title),
                }
            )
        elif request.lock_version is not None:
            lock = request.lock_version  # the one the author saw in the preview
        saved = await workspace.replace_step(
            actor, step_id, plan.content, lock, via_ai=True
        )
        return ApplyResultView(
            kind=output.kind.value,
            created_steps=created,
            step_id=step_id,
            lock_version=int(saved["lock_version"]),
            draft_seq=await self._draft_seq(actor, output.course_id),
        )

    async def _draft_seq(self, actor: Actor, course_id: UUID) -> int | None:
        """The draft counter after the write; the write has happened either way."""
        _, queries, _ = self._ports()
        try:
            detail = await queries.course_detail(course_id, actor)
        except BaseError as exc:
            log.warning("notebooks.apply.draft_seq_failed", error=exc.code)
            return None
        seq = detail.get("draft_seq")
        return seq if isinstance(seq, int) else None
