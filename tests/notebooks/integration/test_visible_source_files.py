"""NB-SHARE: which notebook files a user may reach through MCP."""

from uuid import UUID

from app.modules.notebooks.application.visible_source_files import VisibleSourceFiles
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.domain.sharing import NotebookShare, ShareVia
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import NOW, make_notebook, make_source


async def _with_file(uow_factory: UowFactory, owner: UUID, **fields: object) -> UUID:
    notebook = await make_notebook(uow_factory, owner, **fields)
    file_id = await _add_file(uow_factory, notebook)
    return file_id


async def _add_file(uow_factory: UowFactory, notebook: Notebook) -> UUID:
    file_id = new_id()
    await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.FILE,
        texts=(),
        ref={"file_id": str(file_id)},
        title="notes.pdf",
    )
    return file_id


async def _grant(
    uow_factory: UowFactory, notebook_id: UUID, user_id: UUID, *, revoked: bool = False
) -> None:
    async with uow_factory() as uow:
        await uow.shares.put(
            NotebookShare(
                notebook_id, user_id, ShareVia.DIRECT, NOW, NOW if revoked else None
            )
        )
        await uow.commit()


async def test_own_files_show_and_a_strangers_do_not(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-SHARE: without a grant the files of another person stay out."""
    mine = await _with_file(uow_factory, student.user_id)
    await _with_file(uow_factory, other_student.user_id)

    found = await VisibleSourceFiles(uow_factory).execute(student.user_id)

    assert [(row.file_id, row.shared) for row in found] == [(mine, False)]


async def test_a_grant_shows_the_files_as_shared(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-SHARE: a live grant opens the files of the shared notebook."""
    notebook = await make_notebook(uow_factory, other_student.user_id)
    file_id = await _add_file(uow_factory, notebook)
    await _grant(uow_factory, notebook.id, student.user_id)

    found = await VisibleSourceFiles(uow_factory).execute(student.user_id)

    assert [(row.file_id, row.notebook_id, row.shared) for row in found] == [
        (file_id, notebook.id, True)
    ]


async def test_a_revoked_grant_hides_the_files(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-SHARE: revoking works at once."""
    notebook = await make_notebook(uow_factory, other_student.user_id)
    await _add_file(uow_factory, notebook)
    await _grant(uow_factory, notebook.id, student.user_id, revoked=True)

    assert await VisibleSourceFiles(uow_factory).execute(student.user_id) == []


async def test_deleted_notebooks_are_left_out_for_owner_and_viewer(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-SHARE: a deleted notebook gives no files to anyone."""
    own = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    await _add_file(uow_factory, own)
    shared = await make_notebook(uow_factory, other_student.user_id, deleted_at=NOW)
    await _add_file(uow_factory, shared)
    await _grant(uow_factory, shared.id, student.user_id)

    assert await VisibleSourceFiles(uow_factory).execute(student.user_id) == []


async def test_only_files_with_an_id_count_and_a_hidden_origin_stays_visible_to_owner(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-SHARE: other kinds are skipped; an owner keeps every origin."""
    notebook = await make_notebook(
        uow_factory, student.user_id, origin=NotebookOrigin.FLASHCARDS
    )
    file_id = await _add_file(uow_factory, notebook)
    await make_source(uow_factory, notebook, texts=("Plain text.",), title="Text")

    found = await VisibleSourceFiles(uow_factory).execute(student.user_id)

    assert [row.file_id for row in found] == [file_id]
    assert found[0].origin == NotebookOrigin.FLASHCARDS.value
