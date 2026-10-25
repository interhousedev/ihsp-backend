"""List groups with counts (ADM-6)."""

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_views import build_group_items
from app.modules.academic.application.schedule.results import GroupItemData
from app.shared.contracts.identity import IdentityDirectory


class ListGroups:
    """Return groups with student, subgroup and unregistered counts."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, status: str | None = None) -> list[GroupItemData]:
        """Return groups ordered by name, optionally of one status."""
        async with self.uow_factory() as uow:
            groups = await uow.groups.list_all(status)
            return await build_group_items(uow, self.identity, groups)
