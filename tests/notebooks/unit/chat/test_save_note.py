"""NB-7, NB-15: saving a chat answer as a note source (§ 3.3.6)."""

from app.modules.notebooks.domain.entities import Citation, MessageContent
from app.modules.notebooks.domain.enums import MessageRole, SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceLimitError,
    SourceTooLargeError,
)
from app.modules.notebooks.wiring_chat import ChatServices, build_chat
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_message
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.chat.support import (
    ANSWER,
    ANSWER_TEXT,
    CoreFactory,
    notebook_with_source,
)

import pytest


async def test_an_answer_becomes_a_pending_note_with_its_citations(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-7: the note holds the text with `⟦n⟧` and a copy of the citations."""
    notebook, source = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    note = await chat.save_note.execute(
        student, notebook.id, turn.assistant_message.id, None
    )

    assert note.kind is SourceKind.NOTE
    assert note.body_md == ANSWER_TEXT
    assert note.citations == turn.assistant_message.content.citations
    assert note.title == "Light becomes energy."
    assert note.status is SourceStatus.PENDING
    assert note.selected is True and note.position == source.position + 1
    assert note.notebook_id == notebook.id and note.owner_id == student.user_id
    async with core.uow_factory() as uow:
        stored = await uow.sources.get(note.id)
        counted = await uow.notebooks.get(notebook.id)
    assert stored is not None and stored.body_md == ANSWER_TEXT
    assert stored.citations == note.citations
    assert counted is not None and counted.source_count == 2


async def test_the_note_is_processed_after_the_commit(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """NB-7: `notebooks.process_source` is kicked for the new note."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    note = await chat.save_note.execute(
        student, notebook.id, turn.assistant_message.id, None
    )

    assert kicker.calls == [("notebooks.process_source", {"source_id": str(note.id)})]


async def test_a_given_title_wins_and_is_tidied(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-7: spaces in the title are collapsed."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    note = await chat.save_note.execute(
        student, notebook.id, turn.assistant_message.id, "  My   summary "
    )

    assert note.title == "My summary"


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_an_answer_with_no_words_gets_the_translated_default_title(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    locale: str,
) -> None:
    """NB-7: only chips in the text: the title comes from the user's locale."""
    chat = build_chat(make_core(locale=locale))
    notebook, source = await notebook_with_source(core, student)
    citation = Citation(
        n=1,
        passage_id=new_id(),
        source_id=source.id,
        source_title="Biology",
        source_kind=SourceKind.TEXT,
        snippet="Snippet",
    )
    message = await make_message(
        core.uow_factory,
        notebook,
        role=MessageRole.ASSISTANT,
        content=MessageContent(text="⟦1⟧", citations=[citation]),
    )

    note = await chat.save_note.execute(student, notebook.id, message.id, None)

    assert note.title == core.deps.i18n.t(locale, "notebooks-note-title-answer")
    assert note.body_md == "⟦1⟧"


async def test_a_user_message_cannot_be_saved(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-7: only answers can become notes."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    with pytest.raises(NotebookNotFoundError):
        await chat.save_note.execute(student, notebook.id, turn.user_message.id, None)


async def test_another_students_answer_cannot_be_saved(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    other_student: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """NB-15: 404, nothing is created or kicked."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    mine, _ = await notebook_with_source(core, other_student)

    for path in (notebook.id, mine.id):
        with pytest.raises(NotebookNotFoundError):
            await chat.save_note.execute(
                other_student, path, turn.assistant_message.id, None
            )

    assert kicker.calls == []


async def test_an_answer_of_another_notebook_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-15: the message must belong to the notebook in the path."""
    notebook, _ = await notebook_with_source(core, student)
    elsewhere, _ = await notebook_with_source(core, student)
    answer = await make_message(
        core.uow_factory, elsewhere, role=MessageRole.ASSISTANT, text="Hi"
    )

    with pytest.raises(NotebookNotFoundError):
        await chat.save_note.execute(student, notebook.id, answer.id, None)


async def test_an_answer_without_text_cannot_be_saved(
    core: NotebooksCore, chat: ChatServices, student: Actor, kicker: FakeTaskKicker
) -> None:
    """NB-7: a stopped answer with no text is not a note."""
    notebook, _ = await notebook_with_source(core, student)
    answer = await make_message(
        core.uow_factory, notebook, role=MessageRole.ASSISTANT, text=""
    )

    with pytest.raises(InvalidOptionsError):
        await chat.save_note.execute(student, notebook.id, answer.id, None)

    assert kicker.calls == []


async def test_a_full_notebook_refuses_the_note(
    core: NotebooksCore,
    chat: ChatServices,
    make_core: CoreFactory,
    student: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """NB-1: the source limit applies to notes."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    full = build_chat(make_core(notebooks={"max_sources": 1}))

    with pytest.raises(SourceLimitError):
        await full.save_note.execute(
            student, notebook.id, turn.assistant_message.id, None
        )

    assert kicker.calls == []
    async with core.uow_factory() as uow:
        assert await uow.sources.count_for_notebook(notebook.id) == 1


async def test_a_note_over_the_source_size_cap_is_refused(
    core: NotebooksCore,
    chat: ChatServices,
    make_core: CoreFactory,
    student: Actor,
) -> None:
    """NB-2: the per-source text cap applies to notes."""
    notebook, _ = await notebook_with_source(core, student)
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    small = build_chat(make_core(notebooks={"source_max_chars": 5}))

    with pytest.raises(SourceTooLargeError):
        await small.save_note.execute(
            student, notebook.id, turn.assistant_message.id, None
        )
