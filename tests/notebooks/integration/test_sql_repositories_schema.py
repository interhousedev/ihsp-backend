"""NB-8: constraints of the notebooks schema that no repository method reaches."""

from enum import StrEnum
from typing import cast

from app.modules.notebooks.domain.entities import ArtifactProgress, Notebook
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    GuideStatus,
    MessageRole,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.db.base import Base
from app.shared.ids import new_id
from tests.factories.notebooks import NOW, make_artifact, make_notebook

import pytest
from sqlalchemy import Enum, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

ENUM_COLUMNS = [
    ("notebooks", "summary_status", SummaryStatus),
    ("sources", "kind", SourceKind),
    ("sources", "status", SourceStatus),
    ("sources", "guide_status", GuideStatus),
    ("messages", "role", MessageRole),
    ("artifacts", "kind", ArtifactKind),
    ("artifacts", "status", ArtifactStatus),
]


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


@pytest.mark.parametrize(("table", "column", "domain"), ENUM_COLUMNS)
def test_enum_columns_list_every_value_of_every_phase(
    table: str, column: str, domain: type[StrEnum]
) -> None:
    """NB-8: later phases need no constraint change (slides, url, audio_overview...)."""
    stored = cast(Enum, Base.metadata.tables[f"notebooks.{table}"].c[column].type)

    assert set(stored.enums) == {member.value for member in domain}


async def test_progress_and_files_of_an_output_go_with_the_output(
    uow_factory: UowFactory, db_session: AsyncSession, notebook: Notebook
) -> None:
    """NB-8: deleting the notebook removes the progress and file rows of its outputs."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    async with uow_factory() as uow:
        await uow.progress.upsert(
            ArtifactProgress(artifact.id, notebook.owner_id, {"answers": {}}, NOW)
        )
        await uow.commit()
    await db_session.execute(
        text(
            "INSERT INTO notebooks.artifact_assets "
            "(id, artifact_id, kind, idx, file_id, duration_ms, bytes) "
            "VALUES (:id, :artifact, 'audio_turn', 0, :file, 1500, 2048)"
        ),
        {"id": new_id(), "artifact": artifact.id, "file": new_id()},
    )

    async with uow_factory() as uow:
        await uow.notebooks.hard_delete([notebook.id])
        await uow.commit()

    for table in ("artifact_progress", "artifact_assets"):
        sql = f"SELECT count(*) FROM notebooks.{table} WHERE artifact_id = :id"
        count = await db_session.execute(text(sql), {"id": artifact.id})
        assert count.scalar_one() == 0, table


async def test_an_output_file_slot_is_unique_per_kind_and_index(
    uow_factory: UowFactory, db_session: AsyncSession, notebook: Notebook
) -> None:
    """NB-8: one audio turn per (output, kind, idx)."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.AUDIO_OVERVIEW)
    insert = text(
        "INSERT INTO notebooks.artifact_assets "
        "(id, artifact_id, kind, idx, file_id, duration_ms, bytes) "
        "VALUES (:id, :artifact, 'audio_turn', :idx, :file, 1, 1)"
    )

    def values(idx: int) -> dict[str, object]:
        return {"id": new_id(), "artifact": artifact.id, "idx": idx, "file": new_id()}

    await db_session.execute(insert, values(0))
    await db_session.execute(insert, values(1))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(insert, values(1))


async def test_enumerations_reject_values_outside_the_domain(
    db_session: AsyncSession,
) -> None:
    """NB-8: CHECK constraints guard kind and status columns."""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO notebooks.notebooks (id, owner_id, title, "
                    "summary_status) VALUES (:id, :owner, 't', 'bogus')"
                ),
                {"id": new_id(), "owner": new_id()},
            )
