"""Use case: remove a default material of an EMIS subject id (admin)."""

from uuid import UUID

from app.modules.notebooks.domain.errors import DefaultMaterialNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory


class RemoveDefaultMaterial:
    """Deletes a default material; the copies of students follow on their next sync.

    A copy is a managed source of the subject notebook (like a lesson material), so the
    sync takes it out; a student who excluded it keeps it out until it is restored.
    """

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, edu_subject_id: int, material_id: UUID) -> None:
        """Delete the material of this subject.

        Raises:
            DefaultMaterialNotFoundError: No such material for this subject.
        """
        async with self.uow_factory() as uow:
            material = await uow.default_materials.get(material_id)
            if material is None or material.edu_subject_id != edu_subject_id:
                raise DefaultMaterialNotFoundError()
            await uow.default_materials.delete(material_id)
            await uow.commit()
