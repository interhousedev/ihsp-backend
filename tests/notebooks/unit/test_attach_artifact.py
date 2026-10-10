"""Attach a ready output to a lesson as a file (no database: fakes for the ports)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.modules.notebooks.application.attach_artifact import AttachArtifactToLesson
from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.contracts.links import ResourceRef

import pytest

NOW = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)


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
        self.file_id = uuid4()

    async def store_bytes(self, **kwargs: Any) -> Any:
        self.stored.append(kwargs)
        return SimpleNamespace(id=self.file_id)


class _Links:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def add_lesson_resource(
        self, actor: Actor, lesson_id: Any, *, role: str, file_id: Any
    ) -> ResourceRef:
        self.calls.append((actor, lesson_id, role, file_id))
        return ResourceRef(
            link_id=uuid4(),
            lesson_id=lesson_id,
            role=cast(Any, role),
            kind="file",
            short_url="https://go.test/x",
            title="Cells.docx",
            author_id=actor.user_id,
            author_first_name="Gulnora",
            hidden=False,
            file_id=file_id,
        )


def _setup(
    *, kind: ArtifactKind, status: ArtifactStatus, content: dict[str, Any] | None
) -> tuple[AttachArtifactToLesson, Actor, Artifact, _Files, _Links]:
    teacher = Actor(user_id=uuid4(), roles=frozenset({Role.TEACHER}))
    notebook = Notebook(
        id=uuid4(),
        owner_id=teacher.user_id,
        title="Biology",
        created_at=NOW,
        updated_at=NOW,
    )
    artifact = Artifact(
        id=uuid4(),
        notebook_id=notebook.id,
        owner_id=teacher.user_id,
        kind=kind,
        title="Cells",
        created_at=NOW,
        updated_at=NOW,
        status=status,
        content=content,
    )
    files, links = _Files(), _Links()
    use_case = AttachArtifactToLesson(
        uow_factory=lambda: cast(Any, _Uow(notebook, artifact)),
        files=cast(Any, files),
        links=cast(Any, links),
    )
    return use_case, teacher, artifact, files, links


async def test_a_ready_report_becomes_a_docx_material_of_the_lesson() -> None:
    use_case, teacher, artifact, files, links = _setup(
        kind=ArtifactKind.REPORT,
        status=ArtifactStatus.READY,
        content={"title": "Cells", "markdown": "# Cells\n\n- membrane\n- nucleus"},
    )
    lesson_id = uuid4()

    ref = await use_case.execute(teacher, artifact.notebook_id, artifact.id, lesson_id)

    assert ref.lesson_id == lesson_id
    (stored,) = files.stored
    assert stored["name"] == "Cells.docx"
    assert stored["owner_id"] == teacher.user_id
    assert stored["scope"] is FileScope.STAFF
    assert stored["purpose"] is FilePurpose.LINK
    assert stored["data"][:2] == b"PK"  # a zip container: a real .docx
    assert links.calls == [(teacher, lesson_id, "material", files.file_id)]


async def test_a_student_cannot_attach() -> None:
    use_case, teacher, artifact, files, _ = _setup(
        kind=ArtifactKind.REPORT,
        status=ArtifactStatus.READY,
        content={"markdown": "x"},
    )
    student = Actor(user_id=teacher.user_id, roles=frozenset({Role.STUDENT}))

    with pytest.raises(ForbiddenError):
        await use_case.execute(student, artifact.notebook_id, artifact.id, uuid4())
    assert files.stored == []


async def test_an_output_that_is_not_ready_is_refused() -> None:
    use_case, teacher, artifact, files, _ = _setup(
        kind=ArtifactKind.REPORT, status=ArtifactStatus.GENERATING, content=None
    )

    with pytest.raises(ArtifactNotReadyError):
        await use_case.execute(teacher, artifact.notebook_id, artifact.id, uuid4())
    assert files.stored == []


async def test_a_kind_without_a_file_format_is_refused() -> None:
    use_case, teacher, artifact, files, _ = _setup(
        kind=ArtifactKind.QUIZ, status=ArtifactStatus.READY, content={"questions": []}
    )

    with pytest.raises(InvalidOptionsError):
        await use_case.execute(teacher, artifact.notebook_id, artifact.id, uuid4())
    assert files.stored == []
