"""Text exports and "save to my files" (no database: fakes for the ports)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.modules.notebooks.application.export.render import default_format, export_as
from app.modules.notebooks.application.save_to_files import SaveArtifactToFiles
from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileScope

import pytest

NOW = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)
MIND_MAP = {
    "title": "Cells",
    "nodes": [
        {"id": "n1", "parent_id": None, "label": "Cell", "note": "", "refs": []},
        {"id": "n2", "parent_id": "n1", "label": "Nucleus", "note": "DNA", "refs": []},
    ],
}
QUIZ = {
    "title": "Quiz",
    "questions": [
        {
            "prompt": "What holds DNA?",
            "options": [{"id": "a", "text": "Nucleus"}, {"id": "b", "text": "Wall"}],
            "correct": ["a"],
            "explanation": "The nucleus.",
        }
    ],
}


class _Table:
    def __init__(self, item: Any) -> None:
        self.item = item

    async def get(self, _id: Any) -> Any:
        return self.item


class _Uow:
    def __init__(self, notebook: Notebook, artifact: Artifact) -> None:
        self.notebooks = _Table(notebook)
        self.artifacts = _Table(artifact)

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Files:
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    async def store_bytes(self, **kwargs: Any) -> Any:
        self.stored.append(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs, content_type="x", byte_size=1)


def _setup(
    kind: ArtifactKind,
    content: dict[str, Any] | None,
    status: ArtifactStatus = ArtifactStatus.READY,
    roles: frozenset[Role] = frozenset({Role.STUDENT}),
) -> tuple[SaveArtifactToFiles, Actor, Artifact, _Files]:
    actor = Actor(user_id=uuid4(), roles=roles)
    notebook = Notebook(
        id=uuid4(),
        owner_id=actor.user_id,
        title="Biology",
        created_at=NOW,
        updated_at=NOW,
    )
    artifact = Artifact(
        id=uuid4(),
        notebook_id=notebook.id,
        owner_id=actor.user_id,
        kind=kind,
        title="Cells",
        created_at=NOW,
        updated_at=NOW,
        status=status,
        content=content,
    )
    files = _Files()
    use_case = SaveArtifactToFiles(
        uow_factory=lambda: cast(Any, _Uow(notebook, artifact)), files=cast(Any, files)
    )
    return use_case, actor, artifact, files


def test_default_formats() -> None:
    assert default_format(ArtifactKind.REPORT) == "docx"
    assert default_format(ArtifactKind.MIND_MAP) == "md"
    assert default_format(ArtifactKind.COURSE_PLAN) is None


def test_mind_map_markdown_is_a_nested_list() -> None:
    document = export_as(ArtifactKind.MIND_MAP, "Cells", MIND_MAP, "md")

    assert document.name == "Cells.md"
    text = document.data.decode()
    assert "# Cells" in text
    assert "- Cell\n  - Nucleus - DNA" in text


def test_quiz_markdown_marks_the_correct_option() -> None:
    text = export_as(ArtifactKind.QUIZ, "Quiz", QUIZ, "md").data.decode()

    assert "[x] Nucleus" in text
    assert "[ ] Wall" in text


def test_json_export_keeps_the_content() -> None:
    document = export_as(ArtifactKind.MIND_MAP, "Cells", MIND_MAP, "json")

    assert document.content_type == "application/json"
    assert json.loads(document.data)["nodes"][1]["label"] == "Nucleus"


def test_a_format_the_kind_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError):
        export_as(ArtifactKind.MIND_MAP, "Cells", MIND_MAP, "docx")


async def test_a_mind_map_is_saved_as_markdown_in_the_student_files() -> None:
    use_case, actor, artifact, files = _setup(ArtifactKind.MIND_MAP, MIND_MAP)

    await use_case.execute(actor, artifact.notebook_id, artifact.id)

    (stored,) = files.stored
    assert stored["name"] == "Cells.md"
    assert stored["scope"] is FileScope.STUDENT
    assert stored["purpose"] is FilePurpose.AI_UPLOAD
    assert stored["owner_id"] == actor.user_id


async def test_a_teacher_report_is_saved_as_docx_in_the_staff_scope() -> None:
    use_case, actor, artifact, files = _setup(
        ArtifactKind.REPORT,
        {"title": "Cells", "markdown": "# Cells\n\n- a"},
        roles=frozenset({Role.TEACHER}),
    )

    await use_case.execute(actor, artifact.notebook_id, artifact.id)

    (stored,) = files.stored
    assert stored["name"] == "Cells.docx"
    assert stored["scope"] is FileScope.STAFF
    assert stored["data"][:2] == b"PK"


async def test_not_ready_and_wrong_formats_are_refused() -> None:
    use_case, actor, artifact, files = _setup(
        ArtifactKind.QUIZ, None, status=ArtifactStatus.GENERATING
    )
    with pytest.raises(ArtifactNotReadyError):
        await use_case.execute(actor, artifact.notebook_id, artifact.id)

    use_case, actor, artifact, files = _setup(ArtifactKind.QUIZ, QUIZ)
    with pytest.raises(InvalidOptionsError):
        await use_case.execute(actor, artifact.notebook_id, artifact.id, "pdf")
    course = _setup(ArtifactKind.COURSE_PLAN, {"x": 1})
    with pytest.raises(InvalidOptionsError):
        await course[0].execute(course[1], course[2].notebook_id, course[2].id)
    assert files.stored == [] and course[3].stored == []
