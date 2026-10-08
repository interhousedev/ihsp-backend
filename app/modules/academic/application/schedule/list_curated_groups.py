"""List the groups a teacher curates (STF-12)."""

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_views import build_group_items
from app.modules.academic.application.schedule.results import GroupItemData
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class ListCuratedGroups:
    """Return the active groups where the actor is the curator."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, actor: Actor) -> list[GroupItemData]:
        """Return the actor's groups with counts."""
        async with self.uow_factory() as uow:
            groups = await uow.groups.curated_by(actor.user_id)
            return await build_group_items(uow, self.identity, groups)
