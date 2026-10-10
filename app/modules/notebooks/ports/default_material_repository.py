"""Port: storage of the default materials of EMIS subject ids."""

from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.default_materials import DefaultMaterial


class DefaultMaterialRepository(Protocol):
    """Rows of `subject_default_materials`."""

    async def list_for_subject(self, edu_subject_id: int) -> list[DefaultMaterial]:
        """The default materials of one EMIS subject id, by `position`."""
        ...

    async def list_all(self) -> list[DefaultMaterial]:
        """Every default material, by EMIS subject id and `position`."""
        ...

    async def get(self, material_id: UUID) -> DefaultMaterial | None:
        """The default material with this id."""
        ...

    async def add(self, material: DefaultMaterial) -> None:
        """Insert a default material."""
        ...

    async def delete(self, material_id: UUID) -> None:
        """Delete a default material (copies in notebooks follow on their next sync)."""
        ...
