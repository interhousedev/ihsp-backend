"""Read the subject-to-field map."""

from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class GetFieldMap:
    """`GET /admin/library/unilibrary/field-map`."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Take the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor) -> list[FieldMapEntry]:
        """The whole map."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            return await uow.external.field_map()
