"""Use case: add an empty section to the draft outline (MCP-6)."""

from uuid import UUID

from app.modules.lms.application.authoring.outline_editor import OutlineEditor
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import SectionCreatedView
from app.modules.lms.domain.authoring.course_rules import clean_title
from app.modules.lms.domain.authoring.outline import AddSection
from app.shared.actor import Actor


class CreateSection:
    """Append a section; unlike outline ops from the editor it never conflicts."""

    def __init__(self, uow_factory: UowFactory, editor: OutlineEditor) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.editor = editor

    async def execute(
        self, actor: Actor, course_id: UUID, title: str
    ) -> SectionCreatedView:
        """Add the section on top of the current outline."""
        clean = clean_title(title)
        op = AddSection(op="add_section", title=clean)
        async with self.uow_factory() as uow:
            course, _, created = await self.editor.apply(
                uow, actor, course_id, [op], lock_version=None
            )
            await uow.commit()
        return SectionCreatedView(
            id=created[0],
            title=clean,
            lock_version=course.lock_version,
            draft_seq=course.draft_seq,
        )
