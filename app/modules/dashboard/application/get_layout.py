"""Read a user's dashboard (the default one at version 0)."""

from uuid import UUID

from app.modules.dashboard.domain.layout import Layout, default_widgets
from app.modules.dashboard.ports.unit_of_work import UowFactory


class GetLayout:
    """Return the stored layout or the default."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit-of-work factory."""
        self._uow_factory = uow_factory

    async def execute(self, *, user_id: UUID) -> Layout:
        """Return the layout; version 0 means it was never saved."""
        async with self._uow_factory() as uow:
            layout = await uow.layouts.get(user_id)
        if layout is None:
            return Layout(user_id=user_id, version=0, widgets=default_widgets(user_id))
        return layout
