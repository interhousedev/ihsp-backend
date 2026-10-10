"""SQL repository of the default materials of EMIS subject ids."""

from uuid import UUID

from app.modules.notebooks.domain.default_materials import (
    DefaultMaterial,
    DefaultMaterialKind,
)
from app.modules.notebooks.infrastructure.orm.default_material import (
    SubjectDefaultMaterial as Row,
)

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_material(row: Row) -> DefaultMaterial:
    return DefaultMaterial(
        id=row.id,
        edu_subject_id=int(row.edu_subject_id),
        kind=DefaultMaterialKind(row.kind),
        title=row.title,
        position=int(row.position),
        created_by=row.created_by,
        created_at=row.created_at,
        file_id=row.file_id,
        url=row.url,
        library_item_id=row.library_item_id,
    )


class SqlDefaultMaterialRepository:
    """Default materials of EMIS subject ids."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def list_for_subject(self, edu_subject_id: int) -> list[DefaultMaterial]:
        """The default materials of one EMIS subject id, by `position`."""
        stmt = (
            select(Row)
            .where(Row.edu_subject_id == edu_subject_id)
            .order_by(Row.position, Row.created_at, Row.id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_material(row) for row in rows]

    async def list_all(self) -> list[DefaultMaterial]:
        """Every default material, by EMIS subject id and `position`."""
        stmt = select(Row).order_by(Row.edu_subject_id, Row.position, Row.created_at)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_material(row) for row in rows]

    async def get(self, material_id: UUID) -> DefaultMaterial | None:
        """The default material with this id."""
        row = await self.session.get(Row, material_id)
        return _to_material(row) if row is not None else None

    async def add(self, material: DefaultMaterial) -> None:
        """Insert a default material."""
        self.session.add(
            Row(
                id=material.id,
                edu_subject_id=material.edu_subject_id,
                kind=material.kind.value,
                title=material.title,
                position=material.position,
                created_by=material.created_by,
                created_at=material.created_at,
                file_id=material.file_id,
                url=material.url,
                library_item_id=material.library_item_id,
            )
        )
        await self.session.flush()

    async def delete(self, material_id: UUID) -> None:
        """Delete a default material."""
        await self.session.execute(
            delete(Row).where(Row.id == material_id),
            execution_options={"synchronize_session": False},
        )
