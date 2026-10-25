"""NB-1, NB-2, NB-15: batches, duplicates, limits and who may add what."""

from collections.abc import Callable

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceDuplicateError,
    SourceForbiddenError,
    SourceLimitError,
    SourceTooLargeError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import (
    ChatInput,
    FileInput,
    FlashcardSetInput,
    LessonResourceInput,
    LmsStepInput,
    NoteInput,
    SourceInput,
    TextInput,
    UrlInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import PROCESS_TASK, add_one

import pytest


def _text(n: int, size: int = 20) -> TextInput:
    return TextInput(title=f"Text {n}", text=f"{n} " * (size // 2))


# - - - Batches - - -


async def test_every_accepted_item_is_stored_in_order_and_kicked(
    sources: SourcesServices,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: one request, several sources: consecutive positions, one job each."""
    result = await sources.add_sources.execute(
        student, notebook.id, [_text(1), _text(2), _text(3)]
    )

    assert result.rejected == []
    assert [s.position for s in result.items] == [1, 2, 3]
    assert [s.title for s in result.items] == ["Text 1", "Text 2", "Text 3"]
    assert kicker.calls == [
        (PROCESS_TASK, {"source_id": str(s.id)}) for s in result.items
    ]
    listed = await sources.list_sources.execute(student, notebook.id)
    assert [s.id for s in listed] == [s.id for s in result.items]
    assert all(s.status is SourceStatus.PENDING and s.selected for s in listed)


async def test_a_refused_item_does_not_stop_the_others(
    sources: SourcesServices,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: partial success: the refused index and error are reported."""
    theirs = world.files.add_text(make_file(other_student.user_id), "Not yours.")

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [_text(1), FileInput(file_id=theirs.id), NoteInput(title="N", body_md="Body")],
    )

    assert [s.title for s in result.items] == ["Text 1", "N"]
    assert [s.position for s in result.items] == [1, 2]
    assert [r.index for r in result.rejected] == [1]
    assert isinstance(result.rejected[0].error, SourceForbiddenError)
    assert len(kicker.calls) == 2


async def test_a_batch_where_everything_is_refused_stores_nothing(
    sources: SourcesServices,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-2: no rows, no jobs, and the notebook stays as it was."""
    result = await sources.add_sources.execute(
        student, notebook.id, [FileInput(file_id=new_id()), ChatInput(chat_id=new_id())]
    )

    assert result.items == []
    assert [r.index for r in result.rejected] == [0, 1]
    assert kicker.calls == []
    assert await sources.list_sources.execute(student, notebook.id) == []


@pytest.mark.parametrize("count", [0, 3])
async def test_the_number_of_items_is_limited(
    build: Build, student: Actor, notebook: Notebook, count: int
) -> None:
    """NB-2: an empty request or one over `add_batch_max` is invalid as a whole."""
    sources = build(notebooks={"add_batch_max": 2})

    with pytest.raises(InvalidOptionsError) as raised:
        await sources.add_sources.execute(
            student, notebook.id, [_text(n) for n in range(count)]
        )

    assert raised.value.params == {"field": "items", "max": 2}


async def test_another_students_notebook_is_not_found(
    sources: SourcesServices, student: Actor, their_notebook: Notebook
) -> None:
    """NB-15: a notebook of someone else looks like a missing one."""
    with pytest.raises(NotebookNotFoundError):
        await sources.add_sources.execute(student, their_notebook.id, [_text(1)])


# - - - Duplicates - - -


async def test_the_same_file_twice_in_two_requests_is_a_duplicate(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: the second request reports `source-duplicate` for the file."""
    ref = world.files.add_text(make_file(student.user_id), "Text of the file.")
    await add_one(sources, student, notebook, FileInput(file_id=ref.id))

    result = await sources.add_sources.execute(
        student, notebook.id, [FileInput(file_id=ref.id)]
    )

    assert result.items == []
    assert isinstance(result.rejected[0].error, SourceDuplicateError)
    assert len(await sources.list_sources.execute(student, notebook.id)) == 1


async def test_the_same_chat_twice_in_one_request_is_a_duplicate(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """NB-2: items of one request are compared with each other too."""
    chat = world.chats.add_chat(student.user_id)

    result = await sources.add_sources.execute(
        student, notebook.id, [ChatInput(chat_id=chat.id), ChatInput(chat_id=chat.id)]
    )

    assert len(result.items) == 1
    assert [r.index for r in result.rejected] == [1]
    assert isinstance(result.rejected[0].error, SourceDuplicateError)


async def test_two_spellings_of_one_url_are_a_duplicate(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    """NB-2: the key is the normalised URL."""
    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [
            UrlInput(url="http://Example.com/a"),
            UrlInput(url="http://example.com:80/a#x"),
        ],
    )

    assert len(result.items) == 1
    assert isinstance(result.rejected[0].error, SourceDuplicateError)


async def test_the_same_source_can_be_in_two_notebooks(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: the duplicate key is per notebook."""
    other = await make_notebook(uow_factory, student.user_id)
    found = world.flashcards.add_set(student.user_id)
    item = FlashcardSetInput(set_id=found["id"])

    await add_one(sources, student, notebook, item)
    again = await add_one(sources, student, other, item)

    assert again.notebook_id == other.id


# - - - Limits - - -


async def test_the_51st_source_is_refused(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """NB-1: the source count counts the accepted items of the same request."""
    sources = build(notebooks={"max_sources": 2})

    result = await sources.add_sources.execute(
        student, notebook.id, [_text(1), _text(2), _text(3)]
    )
    later = await sources.add_sources.execute(student, notebook.id, [_text(4)])

    assert len(result.items) == 2
    error = result.rejected[0].error
    assert isinstance(error, SourceLimitError)
    assert error.params == {"limit": 2, "what": "sources"}
    assert isinstance(later.rejected[0].error, SourceLimitError)


async def test_text_over_the_source_cap_is_too_large(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """NB-2: pasted text longer than `source_max_chars` is a 413 for that item."""
    sources = build(notebooks={"source_max_chars": 100})

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [
            TextInput(title="Long", text="x" * 101),
            TextInput(title="Fits", text="x" * 100),
        ],
    )

    assert [s.title for s in result.items] == ["Fits"]
    error = result.rejected[0].error
    assert isinstance(error, SourceTooLargeError)
    assert error.status == 413
    assert error.params == {"limit": 100}


async def test_pasted_text_counts_against_the_notebook_cap_within_a_request(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """NB-2: two texts of 80 characters do not fit a 150 character notebook."""
    sources = build(notebooks={"source_max_chars": 100, "notebook_max_chars": 150})

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [TextInput(title="A", text="a" * 80), TextInput(title="B", text="b" * 80)],
    )

    assert [s.title for s in result.items] == ["A"]
    error = result.rejected[0].error
    assert isinstance(error, SourceLimitError)
    assert error.params == {"limit": 150, "what": "characters"}


async def test_ready_text_counts_against_the_notebook_cap(
    build: Build, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-2: the text already in the notebook is part of the cap."""
    sources = build(notebooks={"source_max_chars": 100, "notebook_max_chars": 150})
    await make_source(uow_factory, notebook, texts=("y" * 100,))

    result = await sources.add_sources.execute(
        student, notebook.id, [TextInput(title="B", text="b" * 80)]
    )

    assert result.items == []
    assert isinstance(result.rejected[0].error, SourceLimitError)


async def test_adding_is_rate_limited_per_student_and_item(
    build: Build,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-2: over the hourly limit an item is refused with a 429; others are not hit."""
    sources = build(limits={"nb_source_adds_per_hour": 2})

    result = await sources.add_sources.execute(
        student, notebook.id, [_text(1), _text(2), _text(3)]
    )
    theirs = await sources.add_sources.execute(
        other_student, their_notebook.id, [_text(4)]
    )

    assert len(result.items) == 2
    assert isinstance(result.rejected[0].error, RateLimitedError)
    assert [r.index for r in result.rejected] == [2]
    assert len(theirs.items) == 1


# - - - Who may add what - - -

Foreign = Callable[[World, Actor, Actor], SourceInput]


def _other_file(world: World, me: Actor, other: Actor) -> SourceInput:
    ref = world.files.add_text(make_file(other.user_id), "Secret.")
    return FileInput(file_id=ref.id)


def _deleted_file(world: World, me: Actor, other: Actor) -> SourceInput:
    ref = world.files.add_text(make_file(me.user_id, status="deleted"), "Gone.")
    return FileInput(file_id=ref.id)


def _missing_file(world: World, me: Actor, other: Actor) -> SourceInput:
    return FileInput(file_id=new_id())


def _other_chat(world: World, me: Actor, other: Actor) -> SourceInput:
    return ChatInput(chat_id=world.chats.add_chat(other.user_id).id)


def _admin_chat(world: World, me: Actor, other: Actor) -> SourceInput:
    return ChatInput(chat_id=world.chats.add_chat(me.user_id, admin=True).id)


def _other_set(world: World, me: Actor, other: Actor) -> SourceInput:
    return FlashcardSetInput(set_id=world.flashcards.add_set(other.user_id)["id"])


def _lesson_without_audience(world: World, me: Actor, other: Actor) -> SourceInput:
    lesson = make_lesson()
    world.schedule.lessons.append(lesson)
    resource = world.links.add(make_resource(lesson.id))
    return LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id)


def _hidden_resource(world: World, me: Actor, other: Actor) -> SourceInput:
    lesson = world.schedule.attend(me.user_id, make_lesson())
    resource = world.links.add(make_resource(lesson.id, hidden=True))
    return LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id)


def _unknown_resource(world: World, me: Actor, other: Actor) -> SourceInput:
    lesson = world.schedule.attend(me.user_id, make_lesson())
    return LessonResourceInput(lesson_id=lesson.id, link_id=new_id())


def _not_enrolled(world: World, me: Actor, other: Actor) -> SourceInput:
    course = world.lms.add_course(enrolled=(other.user_id,))
    step = world.lms.add_step(course)
    return LmsStepInput(course_id=course.id, step_id=step.id)


def _unknown_step(world: World, me: Actor, other: Actor) -> SourceInput:
    course = world.lms.add_course(enrolled=(me.user_id,))
    return LmsStepInput(course_id=course.id, step_id=new_id())


FOREIGN: dict[str, Foreign] = {
    "file_of_another_student": _other_file,
    "deleted_file": _deleted_file,
    "unknown_file": _missing_file,
    "chat_of_another_student": _other_chat,
    "administration_chat": _admin_chat,
    "set_of_another_student": _other_set,
    "lesson_without_audience": _lesson_without_audience,
    "hidden_lesson_resource": _hidden_resource,
    "unknown_lesson_resource": _unknown_resource,
    "course_without_enrolment": _not_enrolled,
    "unknown_lms_step": _unknown_step,
}


@pytest.mark.parametrize("name", sorted(FOREIGN))
async def test_what_the_student_may_not_use_is_forbidden(
    sources: SourcesServices,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    name: str,
) -> None:
    """NB-2, NB-15: the same refusal for missing and foreign objects."""
    item = FOREIGN[name](world, student, other_student)

    result = await sources.add_sources.execute(student, notebook.id, [item])

    assert result.items == []
    assert isinstance(result.rejected[0].error, SourceForbiddenError)


# - - - Kinds that cannot be added - - -


def _file_not_ready(world: World, me: Actor) -> SourceInput:
    ref = world.files.add_text(make_file(me.user_id, status="processing"), "Text.")
    return FileInput(file_id=ref.id)


@pytest.mark.parametrize(
    ("make_item", "hint"),
    [(_file_not_ready, "not_ready")],
)
async def test_a_file_must_be_ready_and_have_text(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
    make_item: Callable[[World, Actor], SourceInput],
    hint: str,
) -> None:
    """NB-2: scans without text and files still being processed are refused."""
    result = await sources.add_sources.execute(
        student, notebook.id, [make_item(world, student)]
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params["hint"] == hint


@pytest.mark.parametrize(
    ("url", "hint"), [("ftp://example.com/a", "scheme"), ("http://", "url")]
)
async def test_only_http_urls_with_a_host_are_accepted(
    sources: SourcesServices, student: Actor, notebook: Notebook, url: str, hint: str
) -> None:
    """NB-2: other schemes and URLs without a host are unsupported."""
    result = await sources.add_sources.execute(
        student, notebook.id, [UrlInput(url=url)]
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params["hint"] == hint


async def test_urls_are_unsupported_without_a_fetcher(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """NB-2: the hint tells the student to paste the text instead."""
    sources = build(fetcher=False)

    result = await sources.add_sources.execute(
        student, notebook.id, [UrlInput(url="http://example.com/a")]
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params["hint"] == "paste_text"


async def test_lms_steps_are_unsupported_without_an_lms(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """NB-2: a deployment without the LMS reader refuses steps as a kind."""
    sources = build(lms=False)
    item = LmsStepInput(course_id=new_id(), step_id=new_id())

    result = await sources.add_sources.execute(student, notebook.id, [item])

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params["hint"] == "kind"


async def test_blank_text_is_an_invalid_option(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    """NB-2: a title or text of spaces only is refused for that item."""
    result = await sources.add_sources.execute(
        student, notebook.id, [TextInput(title="Notes", text="   \n  ")]
    )

    error = result.rejected[0].error
    assert isinstance(error, InvalidOptionsError)
    assert error.params == {"field": "text"}
