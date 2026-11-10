"""NB-AUTO: a subject notebook's title follows the reader's language."""

from app.modules.notebooks.domain.entities import AutoSettings
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook
from tests.fakes.ai.contracts import make_lesson
from tests.fakes.notebooks.schedule import FakeLessonSchedule

import pytest

NAMES = {"ru": "Физика", "uz": "Fizika"}


@pytest.mark.parametrize("user_locale", ["ru", "uz"])
async def test_the_title_is_the_subject_name_in_the_readers_language(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    schedule: FakeLessonSchedule,
    student: Actor,
    user_locale: str,
) -> None:
    """The stored title is kept; list and get show the reader's language."""
    lesson = schedule.attend(student.user_id, make_lesson(subject="Physics"))
    for locale, name in NAMES.items():
        schedule.localize_subject(lesson.subject_id, locale, name)
    notebook = await make_notebook(
        uow_factory,
        student.user_id,
        title="Physics (stored)",
        origin=NotebookOrigin.SUBJECT_AUTO,
        subject_id=lesson.subject_id,
        auto_settings=AutoSettings(),
        subject_title_suffix="",
    )

    opened = await lifecycle.get_notebook.execute(student, notebook.id)
    listed = await lifecycle.list_notebooks.execute(student)

    assert opened.title == NAMES[user_locale]
    assert [n.title for n in listed.items] == [NAMES[user_locale]]
    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
    assert stored is not None and stored.title == "Physics (stored)"


@pytest.mark.parametrize("user_locale", ["ru"])
async def test_a_renamed_notebook_keeps_the_typed_title(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    schedule: FakeLessonSchedule,
    student: Actor,
) -> None:
    """Renaming clears the suffix, so the language no longer changes the title."""
    lesson = schedule.attend(student.user_id, make_lesson(subject="Physics"))
    schedule.localize_subject(lesson.subject_id, "ru", NAMES["ru"])
    notebook = await make_notebook(
        uow_factory,
        student.user_id,
        origin=NotebookOrigin.SUBJECT_AUTO,
        subject_id=lesson.subject_id,
        auto_settings=AutoSettings(),
        subject_title_suffix="",
    )

    renamed = await lifecycle.update_notebook.execute(
        student, notebook.id, {"title": "My notes"}
    )
    opened = await lifecycle.get_notebook.execute(student, notebook.id)

    assert renamed.title == "My notes" and opened.title == "My notes"
    assert opened.subject_title_suffix is None


@pytest.mark.parametrize("user_locale", ["ru"])
async def test_a_renamed_subject_is_reflected_on_the_next_open(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    schedule: FakeLessonSchedule,
    student: Actor,
) -> None:
    """The title is derived from the schedule each time, not frozen."""
    lesson = schedule.attend(student.user_id, make_lesson(subject="Physics"))
    schedule.localize_subject(lesson.subject_id, "ru", "Физика")
    notebook = await make_notebook(
        uow_factory,
        student.user_id,
        origin=NotebookOrigin.SUBJECT_AUTO,
        subject_id=lesson.subject_id,
        auto_settings=AutoSettings(),
        subject_title_suffix="",
    )
    first = await lifecycle.get_notebook.execute(student, notebook.id)

    schedule.localize_subject(lesson.subject_id, "ru", "Физика и астрономия")
    second = await lifecycle.get_notebook.execute(student, notebook.id)

    assert (first.title, second.title) == ("Физика", "Физика и астрономия")
