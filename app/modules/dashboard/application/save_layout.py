"""Save a user's dashboard with optimistic concurrency."""

from uuid import UUID

from app.modules.dashboard.domain.errors import LayoutVersionConflictError
from app.modules.dashboard.domain.layout import Layout, validate_widgets
from app.modules.dashboard.domain.widget import Widget
from app.modules.dashboard.ports.unit_of_work import UowFactory


class SaveLayout:
    """Replace the widgets if the client's version is the stored one."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit-of-work factory."""
        self._uow_factory = uow_factory

    async def execute(
        self, *, user_id: UUID, version: int, widgets: list[Widget]
    ) -> Layout:
        """Return the saved layout with version + 1; raise on a stale version."""
        validate_widgets(widgets)
        async with self._uow_factory() as uow:
            current = await uow.layouts.get(user_id, for_update=True)
            stored = current.version if current else 0
            if version != stored:
                raise LayoutVersionConflictError(params={"version": stored})
            layout = Layout(user_id=user_id, version=stored + 1, widgets=widgets)
            await uow.layouts.save(layout)
            await uow.commit()
        return layout
