"""An in-memory course and its workspace for the course author assistant's tests.

`FakeCourseWorld` plays the LMS (`LmsWorkspace`, `LmsWorkspaceCommands`, the parts of
`LmsQueries` and `LmsDraftCommands` the tools use); `FakeWorkspaceNotebooks` plays
the notebooks module for course workspaces. Both check the ``edit`` permission like
the real modules and log every write.
"""

import hashlib
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
    CourseBrief,
    CourseSectionBrief,
    CourseStepBrief,
    CourseWorkspaceAccess,
    LmsStepText,
)
from app.shared.ids import new_id
from tests.fakes.notebooks.assistant import (
    FakeNotebook,
    FakeNotebooksCommands,
    FakeNotebooksQueries,
    FakeSource,
)

MAX_BLOCKS = 40


@dataclass
class FakeStep:
    """A draft step: title, blocks with ids, lock version and where it came from."""

    course_id: UUID
    title: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    lock_version: int = 0
    via: str = "ui"
    id: UUID = field(default_factory=new_id)


@dataclass
class FakeSection:
    """A section of the draft outline."""

    title: str
    steps: list[UUID] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"s-{new_id().hex[-6:]}")


@dataclass
class FakeCourse:
    """A course with its staff (user id → permissions)."""

    title: str = "Calculus"
    description: str = "Limits and derivatives for grade 11."
    sections: list[FakeSection] = field(default_factory=list)
    staff: dict[UUID, tuple[str, ...]] = field(default_factory=dict)
    draft_seq: int = 1
    id: UUID = field(default_factory=new_id)


def _norm(title: str) -> str:
    return " ".join(title.split()).casefold()


def _with_ids(block: dict[str, Any]) -> dict[str, Any]:
    """Fill empty ids like the LMS does (blocks, questions, options, cards)."""
    filled = dict(block)
    filled["id"] = filled.get("id") or f"b-{new_id().hex[-8:]}"
    for key in ("questions", "cards"):
        if isinstance(filled.get(key), list):
            filled[key] = [
                {**item, "id": item.get("id") or f"i-{new_id().hex[-8:]}"}
                for item in filled[key]
            ]
    return filled


class FakeCourseWorld:
    """The LMS side of the author assistant over `FakeCourse` and `FakeStep`."""

    def __init__(self) -> None:
        """Start without courses."""
        self.courses: dict[UUID, FakeCourse] = {}
        self.steps: dict[UUID, FakeStep] = {}
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.brief_reads = 0

    # - - - arrangement - - -

    def add_course(self, editor: UUID, **fields: Any) -> FakeCourse:
        """Add a course where `editor` holds ``edit``."""
        course = FakeCourse(**fields)
        course.staff.setdefault(editor, (COURSE_EDIT,))
        self.courses[course.id] = course
        return course

    def add_section(self, course: FakeCourse, title: str) -> FakeSection:
        """Append a section to the outline."""
        section = FakeSection(title)
        course.sections.append(section)
        return section

    def add_step(
        self,
        course: FakeCourse,
        section: FakeSection,
        title: str,
        *blocks: dict[str, Any],
    ) -> FakeStep:
        """Append a step with blocks to a section."""
        step = FakeStep(course.id, title, [_with_ids(b) for b in blocks])
        self.steps[step.id] = step
        section.steps.append(step.id)
        return step

    def _require_edit(self, user_id: UUID, course_id: UUID) -> FakeCourse:
        course = self.courses.get(course_id)
        if course is None:
            raise NotFoundError(support_details="course not found")
        if COURSE_EDIT not in course.staff.get(user_id, ()):
            raise ForbiddenError(support_details="no edit permission")
        return course

    # - - - LmsWorkspace - - -

    async def course_access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Staff get their permissions; strangers and unknown courses get None."""
        course = self.courses.get(course_id)
        if course is None or user_id not in course.staff:
            return None
        return CourseWorkspaceAccess(
            course_id=course.id,
            title=course.title,
            description=course.description,
            permissions=course.staff[user_id],
        )

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """Return the outline with ids."""
        self.brief_reads += 1
        course = self.courses.get(course_id)
        if course is None:
            return None
        return CourseBrief(
            course_id=course.id,
            title=course.title,
            description=course.description,
            draft_seq=course.draft_seq,
            sections=tuple(
                CourseSectionBrief(
                    section_id=s.id,
                    title=s.title,
                    steps=tuple(
                        CourseStepBrief(step_id=i, title=self.steps[i].title)
                        for i in s.steps
                    ),
                )
                for s in course.sections
            ),
        )

    async def draft_step_text(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        """Not used by the assistant."""
        raise NotImplementedError

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
        """Create what the outline lacks (titles compared without case)."""
        course = self._require_edit(actor.user_id, course_id)
        plan: list[dict[str, Any]] = []
        created_sections: list[dict[str, Any]] = []
        created_steps: list[dict[str, Any]] = []
        for wanted in sections:
            section = next(
                (
                    s
                    for s in course.sections
                    if _norm(s.title) == _norm(wanted["title"])
                ),
                None,
            )
            row: dict[str, Any] = {
                "title": wanted["title"],
                "section_id": section.id if section else None,
                "action": "exists" if section else "new",
                "steps": [],
            }
            if section is None and not dry_run:
                section = self.add_section(course, wanted["title"])
                row["section_id"] = section.id
                created_sections.append({"id": section.id, "title": section.title})
            for step_in in wanted.get("steps") or []:
                existing = next(
                    (
                        self.steps[i]
                        for i in (section.steps if section else [])
                        if _norm(self.steps[i].title) == _norm(step_in["title"])
                    ),
                    None,
                )
                row["steps"].append(
                    {
                        "title": step_in["title"],
                        "step_id": str(existing.id) if existing else None,
                        "action": "exists" if existing else "new",
                    }
                )
                if existing is None and section is not None and not dry_run:
                    blocks = []
                    if add_briefs and step_in.get("brief"):
                        blocks.append({"type": "text", "markdown": step_in["brief"]})
                    step = self.add_step(course, section, step_in["title"], *blocks)
                    step.via = "ai" if via_ai else "ui"
                    created_steps.append(
                        {
                            "step_id": str(step.id),
                            "section_id": section.id,
                            "title": step.title,
                        }
                    )
            plan.append(row)
        if not dry_run:
            course.draft_seq += 1
            self.writes.append(("apply_outline", {"sections": list(sections)}))
        return {
            "created_sections": created_sections,
            "created_steps": created_steps,
            "existing_sections": sum(1 for r in plan if r["action"] == "exists"),
            "existing_steps": sum(
                1 for r in plan for s in r["steps"] if s["action"] == "exists"
            ),
            "plan": plan,
            "draft_seq": course.draft_seq,
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
        """Replace the draft; a stale lock version is a conflict."""
        step = self.steps.get(step_id)
        if step is None:
            raise NotFoundError(support_details="step not found")
        self._require_edit(actor.user_id, step.course_id)
        if lock_version != step.lock_version:
            raise DraftConflictError(params={"lock_version": step.lock_version})
        ids = [b.get("id") for b in content["blocks"] if b.get("id")]
        if len(ids) != len(set(ids)) or len(content["blocks"]) > MAX_BLOCKS:
            raise ContentInvalidError(params={"reason": "duplicate-ids"})
        step.title = content["title"]
        step.blocks = [_with_ids(b) for b in content["blocks"]]
        step.lock_version += 1
        step.via = "ai" if via_ai else "ui"
        self.writes.append(("replace_step", {"step_id": step_id, **content}))
        return {
            "step_id": str(step.id),
            "blocks": step.blocks,
            "lock_version": step.lock_version,
        }

    # - - - LmsQueries (what the tools use) - - -

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the draft like `StepDraftView` (staff of the step's course only)."""
        step = self.steps.get(step_id)
        if step is None:
            raise NotFoundError(support_details="step not found")
        course = self.courses[step.course_id]
        if actor.user_id not in course.staff:
            raise ForbiddenError(support_details="not course staff")
        return {
            "step_id": str(step.id),
            "course_id": str(step.course_id),
            "content": {"title": step.title, "blocks": list(step.blocks)},
            "lock_version": step.lock_version,
            "status": "changed",
            "updated_via": step.via,
        }

    # - - - LmsDraftCommands (what the tools use) - - -

    async def create_section(
        self, actor: Actor, course_id: UUID, title: str, *, via_mcp: bool
    ) -> dict[str, Any]:
        """Append a section."""
        course = self._require_edit(actor.user_id, course_id)
        section = self.add_section(course, title)
        course.draft_seq += 1
        self.writes.append(("create_section", {"title": title}))
        return {
            "id": section.id,
            "title": title,
            "lock_version": 0,
            "draft_seq": course.draft_seq,
        }

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Append an empty step to a section."""
        course = self._require_edit(actor.user_id, course_id)
        section = next(s for s in course.sections if s.id == section_id)
        step = self.add_step(course, section, title)
        self.writes.append(("create_step", {"section_id": section_id, "title": title}))
        return {
            "step_id": str(step.id),
            "course_id": str(course_id),
            "section_id": section_id,
            "title": title,
            "lock_version": 0,
        }


class FakeWorkspaceNotebooks(FakeNotebooksQueries):
    """Course workspaces as notebooks: staff of the course may read them."""

    def __init__(self, world: FakeCourseWorld) -> None:
        """Share the courses with the LMS fake."""
        super().__init__()
        self.world = world
        self.by_course: dict[UUID, UUID] = {}
        self.contents: dict[UUID, dict[str, Any]] = {}

    def workspace(self, course: FakeCourse, *sources: FakeSource) -> FakeNotebook:
        """Create (or return) the workspace notebook of a course."""
        if course.id in self.by_course:
            book = self.books[self.by_course[course.id]]
            book.sources.extend(sources)
            return book
        book = self.add(
            FakeNotebook(new_id(), f"{course.title} workspace", sources=list(sources))
        )
        self.by_course[course.id] = book.id
        return book

    def ready_output(
        self, course: FakeCourse, kind: str, title: str, content: dict[str, Any]
    ) -> UUID:
        """Add a ready Studio output to the course workspace."""
        book = self.workspace(course)
        artifact_id = new_id()
        book.artifacts.append(
            {"id": str(artifact_id), "kind": kind, "title": title, "status": "ready"}
        )
        self.contents[artifact_id] = {
            "id": str(artifact_id),
            "kind": kind,
            "title": title,
            "status": "ready",
            "content": content,
        }
        return artifact_id

    def _course_of(self, notebook_id: UUID) -> UUID | None:
        return next((c for c, n in self.by_course.items() if n == notebook_id), None)

    def _own(self, user_id: UUID, notebook_id: UUID) -> FakeNotebook | None:
        course_id = self._course_of(notebook_id)
        if course_id is None:
            return super()._own(user_id, notebook_id)
        course = self.world.courses[course_id]
        return self.books[notebook_id] if user_id in course.staff else None

    async def course_workspace(
        self, user_id: UUID, course_id: UUID
    ) -> dict[str, Any] | None:
        """Return the workspace when it exists and the user is staff."""
        notebook_id = self.by_course.get(course_id)
        course = self.world.courses.get(course_id)
        if notebook_id is None or course is None or user_id not in course.staff:
            return None
        return {
            "id": str(notebook_id),
            "title": self.books[notebook_id].title,
            "course_id": str(course_id),
            "can_write": COURSE_EDIT in course.staff[user_id],
        }

    async def get_artifact_content(
        self, user_id: UUID, notebook_id: UUID, artifact_id: UUID
    ) -> dict[str, Any] | None:
        """Return a ready output of a readable workspace."""
        if self._own(user_id, notebook_id) is None:
            return None
        return self.contents.get(artifact_id)


class FakeWorkspaceCommands(FakeNotebooksCommands):
    """Opens workspaces and applies outputs (records what it was asked)."""

    def __init__(self, queries: FakeWorkspaceNotebooks) -> None:
        """Share the workspaces with the queries."""
        super().__init__(queries)
        self.workspaces = queries
        self.opened: list[UUID] = []
        self.applied: list[dict[str, Any]] = []

    async def open_course_workspace(
        self, actor: Actor, course_id: UUID
    ) -> dict[str, Any]:
        """Get or create the workspace (needs ``edit``)."""
        course = self.workspaces.world._require_edit(actor.user_id, course_id)
        book = self.workspaces.workspace(course)
        self.opened.append(course_id)
        return {
            "id": str(book.id),
            "title": book.title,
            "course_id": str(course_id),
            "can_write": True,
        }

    async def apply_artifact(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        *,
        target_step_id: UUID | None = None,
        target_section_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Record the apply and answer like `ApplyResult`."""
        self.applied.append(
            {
                "notebook_id": notebook_id,
                "artifact_id": artifact_id,
                "target_step_id": target_step_id,
                "target_section_id": target_section_id,
                "mode": mode,
            }
        )
        found = self.workspaces.contents[artifact_id]
        return {
            "kind": found["kind"],
            "created_sections": [],
            "created_steps": [],
            "step_id": str(target_step_id) if target_step_id else None,
            "lock_version": None,
            "draft_seq": 2,
        }


def fingerprint(text: str) -> str:
    """A short stable hash for asserting that a prompt part did not change."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]
