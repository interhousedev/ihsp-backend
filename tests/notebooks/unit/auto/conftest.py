"""Fixtures of the auto notebook tests: subject and lesson notebooks over the fakes."""

from typing import cast

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.wiring_auto import AutoServices, build_auto
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.academic import (
    ClassworkQueries,
    LessonRef,
    ScheduleQueries,
)
from app.shared.contracts.files import FilesApi
from app.shared.contracts.links import LinksApi
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources import conftest as shared

import pytest

# The services over the fakes are the ones of the source tests.
build = shared.build
clock = shared.clock
identity = shared.identity
notebook = shared.notebook
scripted_llm = shared.scripted_llm
sleeps = shared.sleeps
sources = shared.sources
their_notebook = shared.their_notebook
user_locale = shared.user_locale
world = shared.world

PAGE = "Photosynthesis turns light into chemical energy in the chloroplasts."


@pytest.fixture
def auto(core: NotebooksCore, sources: SourcesServices, world: World) -> AutoServices:
    """The auto notebook use cases over the fakes of the other modules."""
    return build_auto(
        core,
        readers=sources.readers,
        links=cast(LinksApi, world.links),
        schedule=cast(ScheduleQueries, world.schedule),
        classwork=cast(ClassworkQueries, world.classwork),
        terms=world.terms,
        files=cast(FilesApi, world.files),
    )


@pytest.fixture
def physics(world: World, student: Actor) -> LessonRef:
    """A Physics lesson the student attends."""
    return world.schedule.attend(student.user_id, make_lesson(subject="Physics"))


def teacher_file(world: World, lesson: LessonRef, title: str = "Waves") -> str:
    """A teacher's file material on the lesson with readable text; the link id."""
    ref = world.files.add_text(make_file(lesson.id, name=f"{title}.pdf"), PAGE)
    resource = world.links.add(make_resource(lesson.id, title=title, file_id=ref.id))
    return str(resource.link_id)


def student_file(
    world: World, lesson: LessonRef, author: Actor, title: str = "Slides"
) -> str:
    """A file a student attached to the lesson; the link id."""
    ref = world.files.add_text(make_file(author.user_id, name=f"{title}.pdf"), PAGE)
    resource = world.links.add(
        make_resource(
            lesson.id,
            title=title,
            file_id=ref.id,
            role="attachment",
            author_id=author.user_id,
            author_first_name="Bobur",
        )
    )
    return str(resource.link_id)


async def open_subject(auto: AutoServices, actor: Actor, lesson: LessonRef) -> Notebook:
    """Open the student's notebook of the lesson's subject."""
    return await auto.open_auto_notebook.execute(
        actor, NotebookOrigin.SUBJECT_AUTO, lesson.subject_id
    )
