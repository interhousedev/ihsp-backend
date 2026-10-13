"""HTTP: a lesson attached to a notebook question reaches the model."""

from typing import Any
from uuid import UUID, uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.interfaces.http.v1.notebooks.handlers.attachments import get_lesson_reader
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.test_chat_attachments import LESSON_ID, student_lesson

import pytest
from httpx import AsyncClient

ANSWER = 'It is about light [[S1:P1]].\n<followups>["Why?"]</followups>'


@pytest.fixture
async def notebook(uow_factory: Any, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


@pytest.fixture
async def source(uow_factory: Any, notebook: Notebook) -> Source:
    """A ready source of the notebook."""
    return await make_source(
        uow_factory, notebook, title="Biology", texts=("Light becomes energy.",)
    )


@pytest.fixture
async def lesson_api(
    http_client: Any, services: NotebooksServices, student: Actor
) -> tuple[AsyncClient, list[UUID]]:
    """The notebook routes with a fake lesson reader that records its lessons."""
    asked: list[UUID] = []

    async def read_lesson(lesson_id: UUID, who: Actor) -> dict[str, Any]:
        asked.append(lesson_id)
        return student_lesson()

    client: AsyncClient = await http_client(
        ROUTERS,
        {get_actor: lambda: student, get_lesson_reader: lambda: read_lesson},
        notebooks=services,
    )
    return client, asked


async def test_an_attached_lesson_is_given_to_the_model(
    lesson_api: tuple[AsyncClient, list[UUID]],
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """The topic, the materials and the homework of the lesson reach the model."""
    api, asked = lesson_api
    scripted_llm.queue_text(ANSWER)

    response = await api.post(
        f"/v1/notebooks/{notebook.id}/chat/messages",
        json={
            "text": "Explain this lesson",
            "attachments": [{"kind": "lesson", "id": str(LESSON_ID)}],
        },
    )

    assert response.status_code == 200, response.text
    assert asked == [LESSON_ID]
    question = str(scripted_llm.text_requests[-1]["messages"][-1]["content"])
    assert "Photosynthesis" in question
    assert "Homework: Read pages 10-12" in question


@pytest.mark.parametrize(
    "attachment",
    [
        pytest.param({"kind": "video", "id": str(uuid4())}, id="unknown-kind"),
        pytest.param({"kind": "material", "id": str(uuid4())}, id="no-lesson"),
        pytest.param({"kind": "lesson", "id": "nope"}, id="bad-id"),
    ],
)
async def test_a_malformed_attachment_is_a_validation_error(
    lesson_api: tuple[AsyncClient, list[UUID]],
    notebook: Notebook,
    attachment: dict[str, Any],
) -> None:
    """422 before anything runs."""
    api, asked = lesson_api

    response = await api.post(
        f"/v1/notebooks/{notebook.id}/chat/messages",
        json={"text": "Q?", "attachments": [attachment]},
    )

    assert response.status_code == 422
    assert asked == []
