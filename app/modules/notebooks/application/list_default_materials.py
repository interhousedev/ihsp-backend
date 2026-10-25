"""Use case: the default materials of one EMIS subject id, or of all of them (admin)."""

from app.modules.notebooks.domain.default_materials import DefaultMaterial
from app.modules.notebooks.ports.unit_of_work import UowFactory


class ListDefaultMaterials:
    """Reads the default materials, by subject or every one."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, edu_subject_id: int | None = None) -> list[DefaultMaterial]:
        """The materials of the subject by `position`; every one when no id is given."""
        async with self.uow_factory() as uow:
            if edu_subject_id is None:
                return await uow.default_materials.list_all()
            return await uow.default_materials.list_for_subject(edu_subject_id)
