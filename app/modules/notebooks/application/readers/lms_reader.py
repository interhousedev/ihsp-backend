"""Source kind `lms_step`: a step of an LMS course (§ 3.2.1, LMS-17).

A student's notebook reads the live revision of a step of an enrolled course
(`LmsSourceReader.step_text`). A course workspace reads the *draft* of its own
course's steps (`LmsWorkspace.draft_step_text`, `ref.draft = true`); the draft hash
is the version, so an edited draft makes the source outdated. Only text and flash
card blocks are read, never the questions or answers of test blocks.
"""

from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import (
    SourceForbiddenError,
    SourceReadError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import LmsStepInput, SourceInput
from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.lms import LmsSourceReader, LmsStepText, LmsWorkspace


def is_draft(source: Source) -> bool:
    """True for the draft of a step in a course workspace."""
    return bool(source.ref.get("draft"))


class LmsReader:
    """Reads live steps for students and draft steps for course workspaces."""

    def __init__(
        self, lms: LmsSourceReader | None, workspace: LmsWorkspace | None = None
    ) -> None:
        """Store the LMS readers (either may be missing in a process)."""
        self.lms = lms
        self.workspace = workspace

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """A live step needs an enrollment; a draft step is checked by the caller.

        Unknown ids look the same as forbidden ones.
        """
        item = expect_input(source_input, LmsStepInput)
        if item.draft:
            return await self._resolve_draft(item)
        try:
            step = await self._live(user_id, item.course_id, item.step_id)
        except (ForbiddenError, NotFoundError) as exc:
            raise SourceForbiddenError() from exc
        return ResolvedSource(
            kind=SourceKind.LMS_STEP,
            title=clean_title(f"{step.course_title} / {step.title}", "Course step"),
            ref={"course_id": str(item.course_id), "step_id": str(item.step_id)},
            ref_key=f"lms:{item.step_id}",
            origin={"course_title": step.course_title},
        )

    async def _resolve_draft(self, item: LmsStepInput) -> ResolvedSource:
        """The draft of a step of the workspace's course (the add checked access)."""
        try:
            step = await self._draft(item.course_id, item.step_id)
        except (ForbiddenError, NotFoundError) as exc:
            raise SourceForbiddenError() from exc
        return ResolvedSource(
            kind=SourceKind.LMS_STEP,
            title=clean_title(step.title, "Course step"),
            ref={
                "course_id": str(item.course_id),
                "step_id": str(item.step_id),
                "draft": True,
            },
            ref_key=f"lms-draft:{item.step_id}",
            origin={"course_title": step.course_title, "draft": True},
        )

    async def read(self, source: Source) -> SourceText:
        """The step's text; blocks are the units and the revision is the version."""
        try:
            step = await self._step(source)
        except (ForbiddenError, NotFoundError, SourceUnsupportedError) as exc:
            raise SourceReadError(SourceFailure.FORBIDDEN.value) from exc
        return SourceText(
            text=step.text,
            unit_starts=tuple(step.block_starts),
            upstream_version=step.revision_id,
            ref_update={} if is_draft(source) else {"revision_id": step.revision_id},
        )

    async def current_version(self, source: Source) -> str | None:
        """The live revision id or draft hash (None when it cannot be read)."""
        try:
            return (await self._step(source)).revision_id
        except (ForbiddenError, NotFoundError, SourceUnsupportedError):
            return None

    async def _step(self, source: Source) -> LmsStepText:
        course_id = UUID(str(source.ref["course_id"]))
        step_id = UUID(str(source.ref["step_id"]))
        if is_draft(source):
            return await self._draft(course_id, step_id)
        block_id = source.ref.get("block_id")
        if block_id:  # a video of the step (course notebooks)
            return await self._video(source.owner_id, course_id, step_id, str(block_id))
        return await self._live(source.owner_id, course_id, step_id)

    async def _live(self, user_id: UUID, course_id: UUID, step_id: UUID) -> LmsStepText:
        if self.lms is None:
            raise SourceUnsupportedError(params={"hint": "kind", "kind": "lms_step"})
        return await self.lms.step_text(user_id, course_id, step_id)

    async def _video(
        self, user_id: UUID, course_id: UUID, step_id: UUID, block_id: str
    ) -> LmsStepText:
        if self.lms is None:
            raise SourceUnsupportedError(params={"hint": "kind", "kind": "lms_step"})
        return await self.lms.video_text(user_id, course_id, step_id, block_id)

    async def _draft(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        if self.workspace is None:
            raise SourceUnsupportedError(params={"hint": "kind", "kind": "lms_step"})
        return await self.workspace.draft_step_text(course_id, step_id)
