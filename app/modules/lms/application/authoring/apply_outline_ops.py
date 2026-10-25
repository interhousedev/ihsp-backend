"""Use case: apply outline operations to the draft (LMS-6, UF-LMS-08)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.application.authoring.outline_editor import OutlineEditor
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.outline import OutlineOp
from app.shared.actor import Actor


class ApplyOutlineOps:
    """Add, rename, move and remove sections and steps under the course lock."""

    def __init__(
        self, uow_factory: UowFactory, editor: OutlineEditor, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.editor = editor
        self.presenter = presenter

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        ops: Sequence[OutlineOp],
        *,
        lock_version: int | None,
    ) -> CourseDraftView:
        """Apply the operations; a stale `lock_version` raises a conflict."""
        async with self.uow_factory() as uow:
            course, access, _ = await self.editor.apply(
                uow, actor, course_id, ops, lock_version=lock_version
            )
            await uow.commit()
            return await self.presenter.course_draft(uow, course, access)
