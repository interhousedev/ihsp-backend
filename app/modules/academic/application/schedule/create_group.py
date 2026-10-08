"""Create a group in advance of its first registered student (ADM-6, ACA-1)."""

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_views import build_group_items
from app.modules.academic.application.schedule.results import GroupItemData
from app.modules.academic.domain.schedule.errors import (
    GroupEmisIdTakenError,
    GroupNameTakenError,
)
from app.modules.academic.domain.schedule.group import Group, clean_group_name
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id


class CreateGroup:
    """Create a group with a normalized Latin name and a slug."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(
        self,
        *,
        name: str,
        emis_group_id: int | None = None,
        current_semester: int | None = None,
    ) -> GroupItemData:
        """Insert the group; the slug must be free among active groups."""
        clean, slug = clean_group_name(name)
        async with self.uow_factory() as uow:
            if await uow.groups.find_active_by_slug(slug) is not None:
                raise GroupNameTakenError(params={"name": clean})
            if (
                emis_group_id is not None
                and await uow.groups.get_by_emis_id(emis_group_id) is not None
            ):
                raise GroupEmisIdTakenError(params={"emis_group_id": emis_group_id})
            group = Group(
                id=new_id(),
                name=clean,
                slug=slug,
                emis_group_id=emis_group_id,
                current_semester=current_semester,
            )
            await uow.groups.add(group)
            items = await build_group_items(uow, self.identity, [group])
            await uow.commit()
        return items[0]
