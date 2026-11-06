"""Use case: tests a student writes and edits directly: no model call, no budget (D1).

A test is a `quiz` output, so the Studio page shows it like a generated one. Only the
owner of a personal notebook gets here: this view holds the answers, so neither a
course workspace member nor a person the notebook was shared with may use it.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.create_notebook import CreateNotebook
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.artifacts.kind_support import norm_key
from app.modules.notebooks.domain.artifacts.kinds.quiz import (
    HANDLER,
    MAX_EXACT_COUNT,
    authored_question,
)
from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactLimitError,
    NotebookNotFoundError,
    OutputInvalidError,
    QuizAuthoringError,
)
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id

DEFAULT_NOTEBOOK_KEY: Final = "mcp-tests-notebook-title"
LIST_NOTEBOOKS: Final = 50


def _refuse(reason: str) -> QuizAuthoringError:
    return QuizAuthoringError(params={"reason": reason}, support_details=reason)


def _checked(raw: Mapping[str, Any], question_id: str) -> dict[str, Any]:
    try:
        return authored_question(raw, question_id)
    except OutputInvalidError as exc:
        reason = "; ".join(exc.problems).replace("question 1", question_id)
        raise _refuse(reason or f"{question_id}: invalid") from exc


def _check_whole(questions: Sequence[Mapping[str, Any]]) -> None:
    if not 1 <= len(questions) <= MAX_EXACT_COUNT:
        raise _refuse(f"a test holds 1 to {MAX_EXACT_COUNT} questions")
    keys = [norm_key(str(q["prompt"])) for q in questions]
    if len(set(keys)) != len(keys):
        raise _refuse("two questions have the same prompt")


def _clean_title(title: str) -> str:
    cleaned = title.strip()[:ARTIFACT_TITLE_MAX_CHARS]
    if not cleaned:
        raise _refuse("the title is empty")
    return cleaned


def _view(artifact: Artifact) -> dict[str, Any]:
    questions = (artifact.content or {}).get("questions", [])
    return {
        "id": str(artifact.id),
        "notebook_id": str(artifact.notebook_id),
        "title": artifact.title,
        "question_count": len(questions),
        "questions": questions,
    }


def _edited_questions(
    current: list[dict[str, Any]],
    add: Sequence[Mapping[str, Any]],
    update: Sequence[Mapping[str, Any]],
    delete_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """The new list; every id is checked first and a new question gets a fresh id."""
    known = {str(question["id"]): question for question in current}
    touched = [*(str(change.get("id")) for change in update), *delete_ids]
    if len(set(touched)) != len(touched):
        raise _refuse("a question id appears twice in the batch")
    unknown = sorted(set(touched) - set(known))
    if unknown:
        raise _refuse(f"no question with the id {unknown[0]}")
    changes = {str(change["id"]): change for change in update}
    gone = set(delete_ids)
    kept = [
        (
            _checked({**question, **changes[qid]}, qid)
            if (qid := str(question["id"])) in changes
            else question
        )
        for question in current
        if str(question["id"]) not in gone
    ]
    # Never a number again: saved progress may still name a deleted question.
    added = [_checked(raw, f"q{new_id().hex[-12:]}") for raw in add]
    return [*kept, *added]


class AuthorQuiz:
    """Creates, reads and edits the tests of their owner."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        locale: LocaleResolver,
        create_notebook: CreateNotebook,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.i18n = i18n
        self.locale = locale
        self.create_notebook = create_notebook

    async def list_tests(self, user_id: UUID, *, limit: int) -> list[dict[str, Any]]:
        """Ready tests in the owner's listed notebooks; never their questions."""
        found: list[dict[str, Any]] = []
        async with self.uow_factory() as uow:
            notebooks = await uow.notebooks.list_for_owner(
                user_id, query=None, after=None, limit=LIST_NOTEBOOKS
            )
            for notebook in notebooks:
                rows = await uow.artifacts.list_for_notebook(
                    notebook.id, kind=ArtifactKind.QUIZ, status=ArtifactStatus.READY
                )
                found += [
                    {
                        "id": str(row.id),
                        "notebook_id": str(row.notebook_id),
                        "notebook_title": notebook.title,
                        "title": row.title,
                    }
                    for row in rows
                ]
                if len(found) >= limit:
                    break
        return found[:limit]

    async def get_test(self, user_id: UUID, test_id: UUID) -> dict[str, Any]:
        """The owner's test with its answers; anything else is not found."""
        async with self.uow_factory() as uow:
            return _view(await self._owned(uow, user_id, test_id))

    async def create_test(
        self,
        actor: Actor,
        *,
        notebook_id: UUID | None,
        title: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Store a ready test; without a notebook it goes to the default notebook."""
        clean_title = _clean_title(title)
        stored = [
            _checked(raw, f"q{number}") for number, raw in enumerate(questions, start=1)
        ]
        _check_whole(stored)
        target = notebook_id or await self._default_notebook(actor)
        async with self.uow_factory() as uow:
            notebook = await self._own_notebook(uow, actor.user_id, target)
            limit = self.settings.notebooks.max_artifacts
            if await uow.artifacts.count_live(notebook.id) >= limit:
                raise ArtifactLimitError(params={"limit": limit})
            artifact = self._new_artifact(notebook, clean_title, stored)
            await uow.artifacts.add(artifact)
            await uow.commit()
        return _view(artifact)

    async def edit_questions(
        self,
        user_id: UUID,
        test_id: UUID,
        *,
        add: Sequence[Mapping[str, Any]],
        update: Sequence[Mapping[str, Any]],
        delete_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Apply all changes in one transaction; any refusal changes nothing."""
        async with self.uow_factory() as uow:
            artifact = await self._owned(uow, user_id, test_id, for_update=True)
            content = dict(artifact.content or {})
            questions = _edited_questions(
                list(content.get("questions", [])), add, update, delete_ids
            )
            _check_whole(questions)
            artifact.content = {**content, "questions": questions}
            # It is the student's own text now: it is no longer the shared output.
            artifact.cache_key = None
            artifact.from_cache = False
            artifact.updated_at = self.clock.now()
            await uow.artifacts.save(artifact)
            await uow.commit()
        return _view(artifact)

    def _new_artifact(
        self, notebook: Notebook, title: str, questions: list[dict[str, Any]]
    ) -> Artifact:
        now = self.clock.now()
        options = HANDLER.stored_options(
            HANDLER.parse_options({"count": len(questions)})
        )
        return Artifact(
            id=new_id(),
            notebook_id=notebook.id,
            owner_id=notebook.owner_id,
            kind=ArtifactKind.QUIZ,
            title=title,
            created_at=now,
            updated_at=now,
            status=ArtifactStatus.READY,
            options=options,
            content={"title": title, "questions": questions},
            refs_index={},
            started_at=now,
            finished_at=now,
        )

    async def _default_notebook(self, actor: Actor) -> UUID:
        """The student's notebook for tests without one, found by title or made."""
        locale = await self.locale.locale_of(actor.user_id)
        title = self.i18n.t(locale, DEFAULT_NOTEBOOK_KEY)
        async with self.uow_factory() as uow:
            rows = await uow.notebooks.list_for_owner(
                actor.user_id, query=title, after=None, limit=10
            )
        for row in rows:
            if row.title == title:
                return row.id
        return (await self.create_notebook.execute(actor, title)).id

    @staticmethod
    async def _own_notebook(
        uow: NotebooksUnitOfWork, user_id: UUID, notebook_id: UUID
    ) -> Notebook:
        notebook = await load_notebook(uow, user_id, notebook_id)
        if notebook.is_course_workspace or notebook.owner_id != user_id:
            raise NotebookNotFoundError()
        return notebook

    async def _owned(
        self,
        uow: NotebooksUnitOfWork,
        user_id: UUID,
        test_id: UUID,
        *,
        for_update: bool = False,
    ) -> Artifact:
        artifacts = uow.artifacts
        found = await (
            artifacts.get_for_update(test_id) if for_update else artifacts.get(test_id)
        )
        if (
            found is None
            or found.owner_id != user_id
            or found.kind is not ArtifactKind.QUIZ
            or found.status is not ArtifactStatus.READY
            or found.deleted_at is not None
            or found.content is None
        ):
            raise NotebookNotFoundError()
        await self._own_notebook(uow, user_id, found.notebook_id)
        return found
