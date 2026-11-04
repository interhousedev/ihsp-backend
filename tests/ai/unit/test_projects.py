"""AI projects: a project chat searches only the files attached to its project."""

import json

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.errors import AttachmentInvalidError, ProjectNotFoundError
from tests.ai.conftest import AiHarness
from tests.fakes.ai.contracts import make_file
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest


async def test_a_project_chat_searches_only_the_projects_files(h: AiHarness) -> None:
    """AI projects: search_project_files finds the attached files, never others."""
    attached = h.files.add(make_file(h.student.user_id, name="alpha-plan.pdf"))
    h.files.add(make_file(h.student.user_id, name="alpha-other.pdf"))
    project = await h.services.projects.create(
        h.student, name="Biology", instructions=""
    )
    await h.services.projects.attach_file(h.student, project.id, attached.id)
    chat = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, project_id=project.id
    )
    h.llm.push(
        tool_reply(("search_project_files", {"query": "alpha"})), text_reply("done")
    )

    await h.say(chat.id, "find alpha")

    sent = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    names = [row["name"] for row in sent["untrusted_data"]["items"]]
    assert names == ["alpha-plan.pdf"]


async def test_a_chat_outside_a_project_finds_no_project_files(h: AiHarness) -> None:
    """AI projects: the tool answers with nothing outside a project."""
    h.files.add(make_file(h.student.user_id, name="alpha-plan.pdf"))
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("search_project_files", {"query": "alpha"})), text_reply("done")
    )

    await h.say(chat.id, "find alpha")

    sent = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    assert sent["untrusted_data"]["items"] == []


async def test_projects_are_owner_only(h: AiHarness) -> None:
    """AI projects (IDOR): another student's project looks missing."""
    project = await h.services.projects.create(h.student, name="Mine", instructions="")
    mine = h.files.add(make_file(h.student.user_id))
    theirs = h.files.add(make_file(h.other_student.user_id))

    with pytest.raises(ProjectNotFoundError):
        await h.services.projects.get(h.other_student, project.id)
    with pytest.raises(ProjectNotFoundError):
        await h.services.projects.update(h.other_student, project.id, name="x")
    with pytest.raises(ProjectNotFoundError):
        await h.services.projects.delete(h.other_student, project.id)
    with pytest.raises(ProjectNotFoundError):
        await h.services.projects.attach_file(h.other_student, project.id, mine.id)
    with pytest.raises(AttachmentInvalidError):
        await h.services.projects.attach_file(h.student, project.id, theirs.id)
    with pytest.raises(ProjectNotFoundError):
        await h.services.create_chat.execute(
            actor=h.other_student,
            assistant=Assistant.STUDENT,
            project_id=project.id,
        )
