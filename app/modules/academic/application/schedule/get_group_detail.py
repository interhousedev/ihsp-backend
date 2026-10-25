"""Show a group with its students and subgroups (UF-ADM-04, UF-STF-09)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_access import (
    ensure_curator_or_admin,
)
from app.modules.academic.application.schedule.group_views import build_group_detail
from app.modules.academic.application.schedule.results import GroupDetailData
from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetGroupDetail:
    """Return a group's roster for its curator or Administration."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, actor: Actor, group_id: UUID) -> GroupDetailData:
        """Return the group; names come from the identity module."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            ensure_curator_or_admin(actor, group)
            return await build_group_detail(uow, self.identity, group)
