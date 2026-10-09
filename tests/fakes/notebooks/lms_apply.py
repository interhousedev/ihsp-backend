"""An in-memory LMS draft for the course workspace tests.

One `FakeCourseDraft` plays every LMS port the workspace touches: the course gate
(who may open the workspace), `LmsWorkspace` (outline and draft text for prompts),
`LmsWorkspaceCommands` (outline, replace step), `LmsQueries` (step draft, course) and
`LmsDraftCommands` (new step). It keeps sections, steps, lock versions and a
`draft_seq`, assigns block ids like the LMS and refuses what the LMS refuses (no
`edit`, a stale lock version, an unknown block type).
"""

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    DraftConflictError,
)
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.lms import (
    COURSE_EDIT,
    COURSE_VIEW_DRAFTS,
    CourseBrief,
    CourseSectionBrief,
    CourseStepBrief,
    CourseWorkspaceAccess,
    LmsStepText,
)
from app.shared.ids import new_id

BLOCK_TYPES = ("text", "test", "flashcards")


def norm(title: str) -> str:
    """A title compared without case and extra spaces, like the LMS does."""
    return " ".join(title.split()).casefold()


@dataclass(slots=True)
class FakeStep:
    """A draft step."""

    id: UUID
    section_id: str
    title: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    lock_version: int = 1


@dataclass(slots=True)
class FakeSection:
    """A draft section."""

    id: str
    title: str


class FakeCourseDraft:
    """The draft of one course; `editors` hold `edit`, `viewers` `view_drafts`."""

    def __init__(
        self,
        *,
        title: str = "Biology 10",
        editors: Sequence[UUID] = (),
        viewers: Sequence[UUID] = (),
    ) -> None:
        """Start with an empty draft."""
        self.course_id = new_id()
        self.title = title
        self.editors = set(editors)
        self.viewers = set(viewers)
        self.sections: list[FakeSection] = []
        self.steps: dict[UUID, FakeStep] = {}
        self.draft_seq = 1
        self.calls: list[str] = []
        self.fail_replace_once: Exception | None = None
        self.foreign: set[UUID] = set()  # steps that report another course

    # - - - Setup - - -

    def add_section(self, title: str) -> FakeSection:
        """Add a section to the draft."""
        section = FakeSection(f"sec-{len(self.sections) + 1}", title)
        self.sections.append(section)
        return section

    def add_step(
        self,
        section: FakeSection,
        title: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> FakeStep:
        """Add a step (with blocks, ids assigned) to a section."""
        step = FakeStep(new_id(), section.id, title)
        step.blocks = self._with_ids(blocks or [])
        self.steps[step.id] = step
        return step

    # - - - Helpers - - -

    def _require_edit(self, actor: Actor) -> None:
        if actor.user_id not in self.editors:
            raise ForbiddenError()

    def _step(self, step_id: UUID) -> FakeStep:
        step = self.steps.get(step_id)
        if step is None:
            raise NotFoundError()
        return step

    @staticmethod
    def _with_ids(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Copy the blocks and give every element without an id a fresh one."""
        result = copy.deepcopy(blocks)
        for block in result:
            if block.get("type") not in BLOCK_TYPES:
                raise ContentInvalidError(support_details="unknown block type")
            block["id"] = block.get("id") or new_id().hex[:8]
            for question in block.get("questions") or []:
                question["id"] = question.get("id") or new_id().hex[:8]
                for option in question.get("options") or []:
                    option["id"] = option.get("id") or new_id().hex[:8]
            for card in block.get("cards") or []:
                card["id"] = card.get("id") or new_id().hex[:8]
        return result

    def _section_by_title(self, title: str) -> FakeSection | None:
        return next((s for s in self.sections if norm(s.title) == norm(title)), None)

    # - - - CourseGate / LmsWorkspace - - -

    async def access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Course staff only; a stranger or another course is None."""
        return await self.course_access(user_id, course_id)

    async def course_access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """What the user may do in this course."""
        if course_id != self.course_id:
            return None
        permissions: tuple[str, ...]
        if user_id in self.editors:
            permissions = (COURSE_EDIT, COURSE_VIEW_DRAFTS)
        elif user_id in self.viewers:
            permissions = (COURSE_VIEW_DRAFTS,)
        else:
            return None
        return CourseWorkspaceAccess(self.course_id, self.title, "", permissions)

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """The draft outline."""
        if course_id != self.course_id:
            return None
        sections = tuple(
            CourseSectionBrief(
                s.id,
                s.title,
                tuple(
                    CourseStepBrief(step.id, step.title)
                    for step in self.steps.values()
                    if step.section_id == s.id
                ),
            )
            for s in self.sections
        )
        return CourseBrief(self.course_id, self.title, "", self.draft_seq, sections)

    async def draft_step_text(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        """The Markdown and flash card text of a draft step (no tests)."""
        step = self._step(step_id)
        parts = [
            b.get("markdown") or "\n".join(c["front"] for c in b.get("cards") or [])
            for b in step.blocks
            if b["type"] in ("text", "flashcards")
        ]
        return LmsStepText(
            self.course_id,
            self.title,
            step.id,
            step.title,
            f"draft-{step.lock_version}",
            "\n\n".join(parts),
        )

    # - - - LmsQueries - - -

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        """The draft of a step, in the shape of the LMS `StepDraft`."""
        self.calls.append("step_draft")
        self._require_edit(actor)
        step = self._step(step_id)
        return {
            "step_id": str(step.id),
            "course_id": str(new_id() if step.id in self.foreign else self.course_id),
            "content": {"title": step.title, "blocks": copy.deepcopy(step.blocks)},
            "lock_version": step.lock_version,
            "status": "changed",
            "updated_via": "ui",
        }

    async def course_detail(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """The course draft (only the counter is used)."""
        self.calls.append("course_detail")
        self._require_edit(actor)
        return {"course_id": str(self.course_id), "draft_seq": self.draft_seq}

    # - - - LmsDraftCommands - - -

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add an empty step at the end of a section."""
        self.calls.append("create_step")
        self._require_edit(actor)
        if all(s.id != section_id for s in self.sections):
            raise NotFoundError()
        step = self.add_step(FakeSection(section_id, ""), title)
        self.draft_seq += 1
        return {
            "step_id": str(step.id),
            "course_id": str(self.course_id),
            "section_id": section_id,
            "title": step.title,
            "lock_version": step.lock_version,
        }

    # - - - LmsWorkspaceCommands - - -

    async def apply_outline(
        self,
        actor: Actor,
        course_id: UUID,
        sections: Sequence[dict[str, Any]],
        *,
        dry_run: bool = False,
        add_briefs: bool = False,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Create the sections and steps the draft lacks (matched by title)."""
        self.calls.append("apply_outline_dry" if dry_run else "apply_outline")
        self._require_edit(actor)
        result: dict[str, Any] = {
            "created_sections": [],
            "created_steps": [],
            "existing_sections": 0,
            "existing_steps": 0,
            "plan": [],
        }
        for wanted in sections:
            result["plan"].append(
                self._outline_section(wanted, result, dry_run, add_briefs)
            )
        if not dry_run and (result["created_sections"] or result["created_steps"]):
            self.draft_seq += 1
        result["draft_seq"] = self.draft_seq
        return result

    def _outline_section(
        self,
        wanted: dict[str, Any],
        result: dict[str, Any],
        dry_run: bool,
        add_briefs: bool,
    ) -> dict[str, Any]:
        """Match or create one section of the outline and its steps."""
        section = self._section_by_title(wanted["title"])
        is_new = section is None
        if section is None and not dry_run:
            section = self.add_section(wanted["title"])
            result["created_sections"].append(
                {"id": section.id, "title": section.title}
            )
        result["existing_sections"] += 0 if is_new else 1
        steps = [
            self._outline_step(section, is_new, step, result, dry_run, add_briefs)
            for step in wanted["steps"]
        ]
        return {
            "title": wanted["title"],
            "section_id": section.id if section else None,
            "action": "new" if is_new else "exists",
            "steps": steps,
        }

    def _outline_step(
        self,
        section: FakeSection | None,
        section_is_new: bool,
        wanted: dict[str, Any],
        result: dict[str, Any],
        dry_run: bool,
        add_briefs: bool,
    ) -> dict[str, Any]:
        """Match or create one step of the outline."""
        have = None
        if section is not None and not section_is_new:
            have = next(
                (
                    s
                    for s in self.steps.values()
                    if s.section_id == section.id
                    and norm(s.title) == norm(wanted["title"])
                ),
                None,
            )
        if have is None and section is not None and not dry_run:
            brief = [{"type": "text", "markdown": wanted["brief"]}]
            have = self.add_step(
                section,
                wanted["title"],
                brief if add_briefs and wanted.get("brief") else [],
            )
            result["created_steps"].append(
                {"step_id": str(have.id), "section_id": section.id, "title": have.title}
            )
            action = "new"
        else:
            action = "exists" if have is not None else "new"
            result["existing_steps"] += 1 if have is not None else 0
        return {
            "title": wanted["title"],
            "step_id": str(have.id) if have is not None else None,
            "action": action,
        }

    async def replace_step(
        self,
        actor: Actor,
        step_id: UUID,
        content: dict[str, Any],
        lock_version: int,
        *,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Replace the draft content; a stale lock version is a conflict."""
        self.calls.append("replace_step")
        self._require_edit(actor)
        if self.fail_replace_once is not None:
            error, self.fail_replace_once = self.fail_replace_once, None
            raise error
        step = self._step(step_id)
        if lock_version != step.lock_version:
            raise DraftConflictError(params={"lock_version": step.lock_version})
        step.blocks = self._with_ids(content["blocks"])
        step.title = content["title"]
        step.lock_version += 1
        self.draft_seq += 1
        return {
            "step_id": str(step.id),
            "blocks": copy.deepcopy(step.blocks),
            "lock_version": step.lock_version,
        }
