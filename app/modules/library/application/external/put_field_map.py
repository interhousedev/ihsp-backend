"""Replace the subject-to-field map."""

from collections.abc import Sequence

from app.modules.library.domain.external_errors import FieldMapInvalidError
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class PutFieldMap:
    """`PUT /admin/library/unilibrary/field-map`: replaces the whole table."""

    def __init__(self, uow_factory: UowFactory, academic: AcademicDirectory) -> None:
        """Take the unit of work factory and the subject directory."""
        self.uow_factory = uow_factory
        self.academic = academic

    async def execute(
        self, actor: Actor, entries: Sequence[FieldMapEntry]
    ) -> list[FieldMapEntry]:
        """Store the map; every subject must exist."""
        actor.require(Role.ADMIN)
        subject_ids = list(dict.fromkeys(entry.subject_id for entry in entries))
        known = await self.academic.subject_names(subject_ids, "en")
        unknown = [str(sid) for sid in subject_ids if sid not in known]
        if unknown:
            raise FieldMapInvalidError(params={"subject_ids": unknown})
        async with self.uow_factory() as uow:
            await uow.external.replace_field_map(entries)
            stored = await uow.external.field_map()
            await uow.commit()
        return stored
