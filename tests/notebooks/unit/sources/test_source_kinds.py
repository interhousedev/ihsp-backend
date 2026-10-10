"""NB-2, NB-3, LMS-17: every kind of source, from the request to ready passages."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import GuideStatus, SourceKind, SourceStatus
from app.modules.notebooks.domain.source_input import (
    ChatInput,
    FileInput,
    FlashcardSetInput,
    LessonResourceInput,
    LmsStepInput,
    NoteInput,
    TextInput,
    UrlInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import (
    GUIDE_TASK,
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored_notebook,
)

PAGE_ONE = "Photosynthesis turns light into chemical energy in plants."
PAGE_TWO = "It happens in the chloroplasts, which contain chlorophyll."


async def test_file_is_added_pending_and_read_page_by_page(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-2, NB-3: a file starts `pending` and becomes passages that keep their page."""
    ref = world.files.add_text(
        make_file(student.user_id, name="Biology.pdf"),
        f"{PAGE_ONE}\n\n{PAGE_TWO}",
        page_starts=(0, len(PAGE_ONE) + 2),
    )

    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))

    assert added.kind is SourceKind.FILE
    assert added.status is SourceStatus.PENDING
    assert added.selected is True
    assert added.title == "Biology.pdf"
    assert added.ref == {"file_id": str(ref.id), "content_type": "application/pdf"}
    assert added.ref_key == f"file:{ref.id}"
    assert kicker.calls == [(PROCESS_TASK, {"source_id": str(added.id)})]

    await sources.process_source.execute(added.id)

    ready = await passages_of(uow_factory, added.id)
    assert [(p.seq, p.page) for p in ready] == [(1, 1), (2, 2)]
    assert ready[0].text == PAGE_ONE
    assert kicker.calls[-1] == (GUIDE_TASK, {"source_id": str(added.id)})
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.source_count == 1
    assert saved.char_count == len(PAGE_ONE) + len(PAGE_TWO) + 2
    assert saved.updated_at == clock.now()


async def test_chat_is_read_as_one_passage_per_exchange(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2, NB-3: a chat snapshot ends at its last message, one passage per pair."""
    chat = world.chats.add_chat(student.user_id)

    ready = await add_ready(
        sources, uow_factory, student, notebook, ChatInput(chat_id=chat.id)
    )

    assert ready.kind is SourceKind.CHAT
    assert ready.status is SourceStatus.READY
    assert ready.title == "Photosynthesis"
    assert ready.ref == {"chat_id": str(chat.id), "until_seq": 4}
    assert ready.ref_key == f"chat:{chat.id}"
    assert ready.upstream_version == "4"
    found = await passages_of(uow_factory, ready.id)
    assert len(found) == 2
    assert found[0].text.startswith("User: What is photosynthesis?")
    assert "Assistant: Plants turn light into sugar." in found[0].text
    assert found[1].text.startswith("User: Where does it happen?")


async def test_chat_up_to_a_message_leaves_out_what_came_later(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: `until_seq` cuts the snapshot; later messages are not in the text."""
    chat = world.chats.add_chat(student.user_id)

    ready = await add_ready(
        sources, uow_factory, student, notebook, ChatInput(chat_id=chat.id, until_seq=2)
    )

    assert ready.ref["until_seq"] == 2
    found = await passages_of(uow_factory, ready.id)
    assert len(found) == 1
    assert "Where does it happen?" not in found[0].text


async def test_lesson_file_is_read_like_a_file_and_keeps_its_origin(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: a file of a lesson the student attends; the lesson goes to `origin`."""
    lesson = world.schedule.attend(student.user_id, make_lesson(subject="Physics"))
    ref = world.files.add_text(
        make_file(other_student.user_id, name="Waves.pdf"), PAGE_ONE
    )
    resource = world.links.add(
        make_resource(lesson.id, title="Worksheet", file_id=ref.id)
    )

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id),
    )

    assert ready.kind is SourceKind.LESSON_RESOURCE
    assert ready.status is SourceStatus.READY
    assert ready.title == "Worksheet"
    assert ready.ref["file_id"] == str(ref.id)
    assert ready.ref_key == f"lesson:{resource.link_id}"
    assert ready.origin == {
        "subject": "Physics",
        "lesson_date": lesson.date.isoformat(),
        "topic": "Waves",
        "role": "material",
    }
    assert (await passages_of(uow_factory, ready.id))[0].text == PAGE_ONE


async def test_lesson_link_is_fetched_like_a_web_page(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: a link material is read through the web fetcher."""
    lesson = world.schedule.attend(student.user_id, make_lesson())
    resource = world.links.add(make_resource(lesson.id, title="Article"))
    world.fetcher.add_page(resource.short_url, PAGE_TWO)

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id),
    )

    assert ready.status is SourceStatus.READY
    assert ready.ref["url"] == resource.short_url
    assert world.fetcher.calls == [resource.short_url]
    assert (await passages_of(uow_factory, ready.id))[0].text == PAGE_TWO


async def test_flashcard_set_gives_ten_cards_per_passage(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2, NB-3: `Q:`/`A:` blocks, a new passage at every tenth card."""
    cards = tuple((f"Term {n}", f"Meaning {n}") for n in range(12))
    found = world.flashcards.add_set(student.user_id, "Cell biology", cards)

    ready = await add_ready(
        sources, uow_factory, student, notebook, FlashcardSetInput(set_id=found["id"])
    )

    assert ready.kind is SourceKind.FLASHCARD_SET
    assert ready.title == "Cell biology"
    assert ready.ref_key == f"fc:{found['id']}"
    assert ready.upstream_version
    passages = await passages_of(uow_factory, ready.id)
    assert len(passages) == 2
    assert passages[0].text.startswith("Q: Term 0\nA: Meaning 0")
    assert passages[1].text.startswith("Q: Term 10\nA: Meaning 10")


async def test_lms_step_has_text_and_cards_but_no_test_blocks(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LMS-17, NB-2: questions and correct answers of tests never reach a notebook."""
    course = world.lms.add_course("Biology 10", enrolled=(student.user_id,))
    step = world.lms.add_step(course, "Cells")

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LmsStepInput(course_id=course.id, step_id=step.id),
    )

    assert ready.kind is SourceKind.LMS_STEP
    assert ready.title == "Biology 10 / Cells"
    assert ready.origin == {"course_title": "Biology 10"}
    assert ready.ref_key == f"lms:{step.id}"
    assert ready.upstream_version == "rev-1"
    passages = await passages_of(uow_factory, ready.id)
    assert len(passages) == 2
    text = " ".join(p.text for p in passages)
    assert "basic unit of life" in text
    assert "Mitochondria" in text
    assert "Which answer is correct" not in text
    assert "correct: B" not in text
    assert set(world.lms.calls) == {"step_text"}


async def test_pasted_text_lives_in_the_row_and_has_no_duplicate_key(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: the text is stored in `body_md`; the same text can be added twice."""
    item = TextInput(title="Class notes", text=f"{PAGE_ONE}\n\n{PAGE_TWO}")

    first = await add_ready(sources, uow_factory, student, notebook, item)
    second = await add_one(sources, student, notebook, item)

    assert first.kind is SourceKind.TEXT
    assert first.status is SourceStatus.READY
    assert first.body_md == f"{PAGE_ONE}\n\n{PAGE_TWO}"
    assert first.ref == {}
    assert first.ref_key is None
    assert first.origin is None
    assert second.position == first.position + 1
    assert (await passages_of(uow_factory, first.id))[0].text.startswith(PAGE_ONE)


async def test_note_is_a_source_of_its_own_kind(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-7: a note is a source; its Markdown body is the text."""
    item = NoteInput(title="  My   note ", body_md="# Cells\n\nThe cell is small.")

    ready = await add_ready(sources, uow_factory, student, notebook, item)

    assert ready.kind is SourceKind.NOTE
    assert ready.title == "My note"
    assert ready.status is SourceStatus.READY
    found = await passages_of(uow_factory, ready.id)
    assert found[0].heading == "Cells"


async def test_url_is_normalised_fetched_and_titled_by_its_host(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: scheme and host in lower case, no default port or fragment."""
    world.fetcher.add_page("http://example.com/page", PAGE_ONE, pages=(0,))

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        UrlInput(url=" HTTP://Example.COM:80/page#top "),
    )

    assert ready.kind is SourceKind.URL
    assert ready.title == "example.com"
    assert ready.ref == {"url": "http://example.com/page"}
    assert ready.ref_key == "url:http://example.com/page"
    assert ready.status is SourceStatus.READY
    assert (await passages_of(uow_factory, ready.id))[0].page == 1


async def test_a_ready_source_waits_for_its_guide(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-4: the guide is built by its own job, so it is `none` right after reading."""
    item = TextInput(title="Class notes", text=PAGE_ONE)

    ready = await add_ready(sources, uow_factory, student, notebook, item)

    assert ready.guide is None
    assert ready.guide_status is GuideStatus.NONE
