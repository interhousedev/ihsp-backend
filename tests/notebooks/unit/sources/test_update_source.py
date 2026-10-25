"""NB-5, NB-7: rename, tick and edit the text of a source."""

from typing import Any

from app.modules.notebooks.domain.entities import (
    Citation,
    Notebook,
    Source,
    SourceGuide,
)
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceLimitError,
    SourceNotReadyError,
    SourceTooLargeError,
)
from app.modules.notebooks.domain.source_input import (
    FileInput,
    NoteInput,
    TextInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_source
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import (
    GUIDE_TASK,
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
    stored_notebook,
)

import pytest

OLD = "A short note about cells."
NEW = (
    "# Cells\n\nThe cell is the unit of life.\n\n# Organelles\n\nThe nucleus holds DNA."
)


async def _note(
    sources: SourcesServices, uow_factory: UowFactory, student: Actor, nb: Notebook
) -> Source:
    return await add_ready(
        sources, uow_factory, student, nb, NoteInput(title="Cells", body_md=OLD)
    )


# - - - Title and checkbox - - -


async def test_renaming_cleans_the_title_and_starts_no_job(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-5: a one-line title; the text and the status stay as they are."""
    note = await _note(sources, uow_factory, student, notebook)
    queued = len(kicker.calls)

    changed = await sources.update_source.execute(
        student, notebook.id, note.id, {"title": "  Cell   notes \n"}
    )

    assert changed.title == "Cell notes"
    assert (await stored(uow_factory, note.id)).title == "Cell notes"
    assert changed.status is SourceStatus.READY
    assert len(kicker.calls) == queued


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "x" * 256}, "title"),
        ({"title": 5}, "title"),
        ({"selected": "yes"}, "selected"),
        ({"body_md": "   "}, "body_md"),
        ({"status": "ready"}, "status"),
    ],
)
async def test_invalid_changes_are_refused_before_anything_is_stored(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    changes: dict[str, Any],
    field: str,
) -> None:
    """NB-5: unknown or invalid fields are `invalid-options` with the field name."""
    note = await _note(sources, uow_factory, student, notebook)

    with pytest.raises(InvalidOptionsError) as raised:
        await sources.update_source.execute(student, notebook.id, note.id, changes)

    assert raised.value.params == {"field": field}
    assert (await stored(uow_factory, note.id)).title == "Cells"


async def test_unticking_the_last_source_clears_the_summary(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-5, NB-4: no selected source, no summary; ticking it makes it due again."""
    note = await _note(sources, uow_factory, student, notebook)
    assert (
        await stored_notebook(uow_factory, notebook.id)
    ).summary_status is SummaryStatus.STALE

    await sources.update_source.execute(
        student, notebook.id, note.id, {"selected": False}
    )
    cleared = await stored_notebook(uow_factory, notebook.id)
    assert (cleared.summary_status, cleared.summary_due_at) == (
        SummaryStatus.NONE,
        None,
    )

    await sources.update_source.execute(
        student, notebook.id, note.id, {"selected": True}
    )
    due = await stored_notebook(uow_factory, notebook.id)
    assert due.summary_status is SummaryStatus.STALE
    assert due.summary_due_at is not None


# - - - Editing the text - - -


async def test_editing_a_note_rechunks_it_and_builds_a_new_guide(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-7, NB-3: the note goes back to `pending`; the job rebuilds its data."""
    note = await _note(sources, uow_factory, student, notebook)
    old_ids = {p.id for p in await passages_of(uow_factory, note.id)}
    async with uow_factory() as uow:
        row = await uow.sources.get_for_update(note.id)
        assert row is not None
        row.guide = SourceGuide(summary="Old guide.")
        row.guide_status = GuideStatus.READY
        await uow.sources.save(row)
        await uow.commit()

    edited = await sources.update_source.execute(
        student, notebook.id, note.id, {"body_md": NEW}
    )

    assert edited.status is SourceStatus.PENDING
    assert edited.body_md == NEW
    assert kicker.calls[-1] == (PROCESS_TASK, {"source_id": str(note.id)})
    assert (await stored_notebook(uow_factory, notebook.id)).char_count == 0

    await sources.process_source.execute(note.id)

    fresh = await stored(uow_factory, note.id)
    assert fresh.status is SourceStatus.READY
    assert fresh.content_hash != note.content_hash
    assert (fresh.guide, fresh.guide_status) == (None, GuideStatus.NONE)
    assert kicker.names().count(GUIDE_TASK) == 2
    found = await passages_of(uow_factory, note.id)
    assert old_ids.isdisjoint({p.id for p in found})
    assert [p.heading for p in found] == ["Cells", "Organelles"]
    assert (await stored_notebook(uow_factory, notebook.id)).char_count == len(NEW)


async def test_saving_the_same_text_changes_nothing(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-7: an unchanged body does not trigger processing."""
    note = await _note(sources, uow_factory, student, notebook)
    queued = len(kicker.calls)

    same = await sources.update_source.execute(
        student, notebook.id, note.id, {"body_md": OLD}
    )

    assert same.status is SourceStatus.READY
    assert len(kicker.calls) == queued


async def test_the_text_of_a_pending_source_cannot_be_edited_yet(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    """NB-7: `source-not-ready` for the text; the title can still be changed."""
    pending = await add_one(
        sources, student, notebook, TextInput(title="Draft", text=OLD)
    )

    with pytest.raises(SourceNotReadyError):
        await sources.update_source.execute(
            student, notebook.id, pending.id, {"body_md": NEW}
        )
    renamed = await sources.update_source.execute(
        student, notebook.id, pending.id, {"title": "Final"}
    )

    assert renamed.title == "Final"
    assert renamed.body_md == OLD


async def test_only_text_and_notes_without_citations_can_be_edited(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-7: files and notes saved from an answer keep their text."""
    ref = world.files.add_text(make_file(student.user_id), OLD)
    file_source = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    cited = await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.NOTE,
        texts=(OLD,),
        body_md=OLD,
        citations=[
            Citation(
                n=1,
                passage_id=new_id(),
                source_id=new_id(),
                source_title="Biology",
                source_kind=SourceKind.FILE,
                snippet=OLD,
            )
        ],
    )

    for source in (file_source, cited):
        with pytest.raises(InvalidOptionsError) as raised:
            await sources.update_source.execute(
                student, notebook.id, source.id, {"body_md": NEW}
            )
        assert raised.value.params == {"field": "body_md"}


async def test_an_edit_over_the_caps_is_refused(
    build: Build,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-7, NB-2: the new text must fit the source cap and the notebook cap."""
    sources = build(notebooks={"source_max_chars": 100, "notebook_max_chars": 150})
    await make_source(uow_factory, notebook, texts=("y" * 100,))
    note = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        NoteInput(title="Small", body_md="n" * 50),
    )

    with pytest.raises(SourceTooLargeError):
        await sources.update_source.execute(
            student, notebook.id, note.id, {"body_md": "n" * 101}
        )
    with pytest.raises(SourceLimitError):
        await sources.update_source.execute(
            student, notebook.id, note.id, {"body_md": "n" * 80}
        )
    fits = await sources.update_source.execute(
        student, notebook.id, note.id, {"body_md": "n" * 40}
    )

    assert fits.status is SourceStatus.PENDING


async def test_only_the_owner_can_change_a_source(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """NB-15: another student gets a 404 and nothing changes."""
    note = await _note(sources, uow_factory, student, notebook)

    with pytest.raises(NotebookNotFoundError):
        await sources.update_source.execute(
            other_student, notebook.id, note.id, {"title": "Mine now"}
        )

    assert (await stored(uow_factory, note.id)).title == "Cells"
