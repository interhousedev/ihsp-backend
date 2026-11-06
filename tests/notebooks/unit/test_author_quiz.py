"""MCP A2 (D1): tests written directly, stored as quiz outputs, for their owner only."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.author_quiz import AuthorQuiz
from app.modules.notebooks.application.create_notebook import CreateNotebook
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    NotebookOrigin,
)
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    QuizAuthoringError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_artifact, make_notebook

import pytest


def question(prompt: str = "2 + 2?", **changes: Any) -> dict[str, Any]:
    return {
        "type": "single",
        "prompt": prompt,
        "options": [{"id": "x", "text": "4"}, {"id": "y", "text": "5"}],
        "correct": ["x"],
        "explanation": "Two and two make four.",
        **changes,
    }


@pytest.fixture
def author(core: NotebooksCore, uow_factory: UowFactory) -> AuthorQuiz:
    deps = core.deps
    return AuthorQuiz(
        uow_factory=uow_factory,
        clock=deps.clock,
        settings=deps.settings,
        i18n=deps.i18n,
        locale=core.locale,
        create_notebook=CreateNotebook(
            uow_factory=uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            i18n=deps.i18n,
            locale=core.locale,
        ),
    )


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    return await make_notebook(uow_factory, student.user_id)


async def _make(
    author: AuthorQuiz, student: Actor, notebook: Notebook
) -> dict[str, Any]:
    return await author.create_test(
        student,
        notebook_id=notebook.id,
        title="Maths",
        questions=[question(), question("3 + 3?")],
    )


async def test_create_stores_a_ready_quiz_the_web_page_can_open(
    author: AuthorQuiz, student: Actor, notebook: Notebook, uow_factory: UowFactory
) -> None:
    """D1: a ready `quiz` output with the stored question shape and no model data."""
    made = await _make(author, student, notebook)

    async with uow_factory() as uow:
        stored = await uow.artifacts.get(UUID(made["id"]))
    assert stored is not None
    assert stored.kind is ArtifactKind.QUIZ
    assert stored.status is ArtifactStatus.READY
    assert stored.model is None
    assert stored.content is not None
    first = stored.content["questions"][0]
    assert first["id"] == "q1"
    assert [o["id"] for o in first["options"]] == ["a", "b"]
    assert first["correct"] == ["a"]
    assert first["difficulty"] == "medium"


async def test_without_a_notebook_one_default_notebook_is_used(
    author: AuthorQuiz, student: Actor
) -> None:
    """D1: two tests without a notebook land in the same notebook."""
    first = await author.create_test(
        student, notebook_id=None, title="A", questions=[question()]
    )
    second = await author.create_test(
        student, notebook_id=None, title="B", questions=[question()]
    )

    assert first["notebook_id"] == second["notebook_id"]


@pytest.mark.parametrize(
    "broken",
    [
        {"correct": ["nope"]},
        {"correct": ["x", "y"]},
        {"explanation": " "},
        {"options": [{"id": "x", "text": "4"}]},
        {"options": [{"id": "x", "text": "Option A"}, {"id": "y", "text": "5"}]},
    ],
)
async def test_an_invalid_question_is_refused_and_nothing_is_stored(
    author: AuthorQuiz,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    broken: dict[str, Any],
) -> None:
    """D1: authored questions follow the rules of generated ones."""
    with pytest.raises(QuizAuthoringError):
        await author.create_test(
            student,
            notebook_id=notebook.id,
            title="T",
            questions=[question(), question("other?", **broken)],
        )

    async with uow_factory() as uow:
        assert await uow.artifacts.count_live(notebook.id) == 0


async def test_duplicate_prompts_and_an_empty_test_are_refused(
    author: AuthorQuiz, student: Actor, notebook: Notebook
) -> None:
    """D1: a test holds distinct questions, at least one."""
    with pytest.raises(QuizAuthoringError):
        await author.create_test(
            student,
            notebook_id=notebook.id,
            title="T",
            questions=[question(), question()],
        )
    with pytest.raises(QuizAuthoringError):
        await author.create_test(
            student, notebook_id=notebook.id, title="T", questions=[]
        )


async def test_someone_elses_notebook_is_not_found(
    author: AuthorQuiz, other_student: Actor, notebook: Notebook
) -> None:
    """Rule 2: another student's notebook answers like a missing one."""
    with pytest.raises(NotebookNotFoundError):
        await author.create_test(
            other_student, notebook_id=notebook.id, title="T", questions=[question()]
        )


async def test_batch_edit_adds_updates_deletes_and_keeps_ids(
    author: AuthorQuiz, student: Actor, notebook: Notebook
) -> None:
    """MCP A2: stable ids; a new id is never a reused number."""
    made = await _make(author, student, notebook)

    edited = await author.edit_questions(
        student.user_id,
        UUID(made["id"]),
        add=[question("4 + 4?")],
        update=[{"id": "q1", "prompt": "Two plus two?"}],
        delete_ids=["q2"],
    )

    ids = [q["id"] for q in edited["questions"]]
    assert ids[0] == "q1"
    assert edited["questions"][0]["prompt"] == "Two plus two?"
    assert edited["questions"][0]["correct"] == ["a"]
    assert "q2" not in ids
    assert ids[1] not in {"q1", "q2", "q3"}


@pytest.mark.parametrize(
    "batch",
    [
        {"update": [{"id": "q9", "prompt": "x?"}]},
        {"delete_ids": ["q9"]},
        {"update": [{"id": "q1", "correct": ["zzz"]}], "delete_ids": ["q2"]},
        {"update": [{"id": "q1", "prompt": "x?"}], "delete_ids": ["q1"]},
        {"delete_ids": ["q1", "q2"]},
    ],
)
async def test_a_refused_batch_changes_nothing(
    author: AuthorQuiz,
    student: Actor,
    notebook: Notebook,
    batch: dict[str, Any],
) -> None:
    """MCP A2: the batch is atomic."""
    made = await _make(author, student, notebook)
    test_id = UUID(made["id"])
    args: dict[str, Any] = {"add": [], "update": [], "delete_ids": [], **batch}

    with pytest.raises(QuizAuthoringError):
        await author.edit_questions(student.user_id, test_id, **args)

    assert await author.get_test(student.user_id, test_id) == made


async def test_an_edit_leaves_the_shared_cache_of_a_generated_quiz(
    author: AuthorQuiz, student: Actor, notebook: Notebook, uow_factory: UowFactory
) -> None:
    """MCP A2: the edited copy no longer claims to be the shared output."""
    stored = question()
    stored.update(id="q1", options=[{"id": "a", "text": "4"}, {"id": "b", "text": "5"}])
    stored["correct"] = ["a"]
    artifact = await make_artifact(
        uow_factory,
        notebook,
        kind=ArtifactKind.QUIZ,
        content={"title": "T", "questions": [stored]},
        cache_key="k" * 64,
        from_cache=True,
    )

    await author.edit_questions(
        student.user_id,
        artifact.id,
        add=[],
        update=[{"id": "q1", "prompt": "Mine?"}],
        delete_ids=[],
    )

    async with uow_factory() as uow:
        found = await uow.artifacts.get(artifact.id)
    assert found is not None and found.cache_key is None and not found.from_cache


async def test_reading_and_editing_are_for_the_owner_only(
    author: AuthorQuiz,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """Rule 2: the same not found for a foreign, a missing and a random id."""
    made = await _make(author, student, notebook)
    test_id = UUID(made["id"])

    for wrong_user, wrong_id in (
        (other_student.user_id, test_id),
        (student.user_id, new_id()),
    ):
        with pytest.raises(NotebookNotFoundError):
            await author.get_test(wrong_user, wrong_id)
        with pytest.raises(NotebookNotFoundError):
            await author.edit_questions(
                wrong_user, wrong_id, add=[question("x?")], update=[], delete_ids=[]
            )


async def test_another_kind_of_output_is_not_a_test(
    author: AuthorQuiz, student: Actor, notebook: Notebook, uow_factory: UowFactory
) -> None:
    """D1: a report of the same owner is not reachable here."""
    report = await make_artifact(uow_factory, notebook, kind=ArtifactKind.REPORT)

    with pytest.raises(NotebookNotFoundError):
        await author.get_test(student.user_id, report.id)


async def test_a_course_workspace_never_shows_answers_through_this_view(
    author: AuthorQuiz, student: Actor, uow_factory: UowFactory
) -> None:
    """Security: a workspace output is not a student's personal test."""
    workspace = await make_notebook(
        uow_factory,
        student.user_id,
        origin=NotebookOrigin.COURSE,
        course_id=new_id(),
    )
    quiz = await make_artifact(
        uow_factory,
        workspace,
        kind=ArtifactKind.QUIZ,
        content={"title": "T", "questions": [question(id="q1")]},
    )

    with pytest.raises(NotebookNotFoundError):
        await author.get_test(student.user_id, quiz.id)


async def test_list_gives_ready_tests_without_questions(
    author: AuthorQuiz,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """D1: titles only, of the owner's ready quizzes."""
    made = await _make(author, student, notebook)
    await make_artifact(uow_factory, notebook, kind=ArtifactKind.REPORT)
    await make_artifact(
        uow_factory, notebook, kind=ArtifactKind.QUIZ, status=ArtifactStatus.GENERATING
    )

    listed = await author.list_tests(student.user_id, limit=10)

    assert [row["id"] for row in listed] == [made["id"]]
    assert "questions" not in listed[0]
    assert await author.list_tests(other_student.user_id, limit=10) == []
