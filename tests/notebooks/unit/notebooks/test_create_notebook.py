"""NB-1: creating a notebook (default title, limits, ownership)."""

from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookLimitError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook
from tests.fakes.clock import FixedClock

import pytest


@pytest.mark.parametrize(
    ("user_locale", "title"),
    [
        ("en", "Untitled notebook"),
        ("ru", "Новый блокнот"),
        ("uz", "Yangi daftar"),
    ],
)
async def test_default_title_follows_the_locale_of_the_user(
    lifecycle: NotebooksLifecycleServices, student: Actor, title: str
) -> None:
    """NB-1: without a title the notebook is named in the student's language."""
    notebook = await lifecycle.create_notebook.execute(student)

    assert notebook.title == title
    assert notebook.title_auto is True
    assert notebook.emoji is None
    assert notebook.emoji_auto is True


async def test_created_notebook_is_stored_for_the_owner_with_empty_counters(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-1: the stored notebook belongs to the student and has no sources yet."""
    notebook = await lifecycle.create_notebook.execute(student)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
    assert stored == notebook
    assert notebook.owner_id == student.user_id
    assert notebook.created_at == notebook.updated_at == clock.now()
    assert notebook.last_opened_at == clock.now()
    assert (notebook.source_count, notebook.char_count) == (0, 0)
    assert (notebook.ready_source_count, notebook.selected_source_count) == (0, 0)
    assert notebook.pinned is False
    assert notebook.deleted_at is None


async def test_given_title_and_emoji_are_the_students_own(
    lifecycle: NotebooksLifecycleServices, student: Actor
) -> None:
    """NB-1: a title or emoji given at creation is never replaced by the AI."""
    notebook = await lifecycle.create_notebook.execute(student, "  Biology 10  ", "🌱")

    assert notebook.title == "Biology 10"
    assert notebook.title_auto is False
    assert notebook.emoji == "🌱"
    assert notebook.emoji_auto is False


async def test_only_an_emoji_keeps_the_default_title_automatic(
    lifecycle: NotebooksLifecycleServices, student: Actor
) -> None:
    """NB-1: the two auto flags are independent."""
    notebook = await lifecycle.create_notebook.execute(student, None, "📚")

    assert notebook.title == "Untitled notebook"
    assert notebook.title_auto is True
    assert notebook.emoji_auto is False


@pytest.mark.parametrize("blank", ["", "   "])
async def test_blank_title_is_the_same_as_no_title(
    lifecycle: NotebooksLifecycleServices, student: Actor, blank: str
) -> None:
    """NB-1: an empty title field creates an automatic notebook."""
    notebook = await lifecycle.create_notebook.execute(student, blank, "")

    assert notebook.title == "Untitled notebook"
    assert notebook.title_auto is True
    assert notebook.emoji is None
    assert notebook.emoji_auto is True


async def test_title_may_have_120_characters_but_not_121(
    lifecycle: NotebooksLifecycleServices, student: Actor
) -> None:
    """NB-1: the title limit is 120 characters."""
    notebook = await lifecycle.create_notebook.execute(student, "t" * 120)
    assert len(notebook.title) == 120

    with pytest.raises(InvalidOptionsError) as caught:
        await lifecycle.create_notebook.execute(student, "t" * 121)
    assert caught.value.params == {"field": "title"}


async def test_emoji_longer_than_16_characters_is_refused(
    lifecycle: NotebooksLifecycleServices, student: Actor
) -> None:
    """NB-1: the emoji column holds 16 characters."""
    with pytest.raises(InvalidOptionsError) as caught:
        await lifecycle.create_notebook.execute(student, None, "x" * 17)
    assert caught.value.params == {"field": "emoji"}


async def test_the_51st_notebook_is_refused(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-1: a student keeps at most 50 notebooks."""
    for _ in range(50):
        await make_notebook(uow_factory, student.user_id)

    with pytest.raises(NotebookLimitError) as caught:
        await lifecycle.create_notebook.execute(student)

    assert caught.value.status == 409
    assert caught.value.params == {"limit": 50}


async def test_deleted_notebooks_and_other_users_do_not_count_against_the_limit(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    clock: FixedClock,
) -> None:
    """NB-1: only the student's own live notebooks fill the 50 places."""
    for _ in range(49):
        await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())
    for _ in range(10):
        await make_notebook(uow_factory, other_student.user_id)

    last = await lifecycle.create_notebook.execute(student)

    assert last.owner_id == student.user_id
    with pytest.raises(NotebookLimitError):
        await lifecycle.create_notebook.execute(student)
