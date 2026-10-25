"""LMS-22, MCP-6, UF-LMS-16: add-only draft commands and read queries for MCP."""

import json
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    CoursePermissionError,
)
from app.modules.lms.infrastructure.orm import TestAttempt as AttemptRow
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    content_of,
    publish,
    quiz_block,
    seed_published,
    single_question,
    step_row,
    text_block,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_an_ai_client_drafts_a_section_a_step_blocks_and_questions(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-16: everything lands in the draft as pending changes via MCP."""
    owner = course.team.owner
    commands = services.draft_commands

    section = await commands.create_section(
        owner, course.id, "Derivatives", via_mcp=True
    )
    step = await commands.create_step(
        owner, course.id, section["id"], "Rules", via_mcp=True
    )
    text = await commands.add_block(
        owner, UUID(step["step_id"]), text_block("# Rules"), via_mcp=True
    )
    quiz = await commands.add_block(
        owner, UUID(step["step_id"]), quiz_block(), via_mcp=True
    )
    question = await commands.add_question(
        owner, UUID(step["step_id"]), quiz["block_id"], single_question(), via_mcp=True
    )

    draft = await services.get_step_draft.execute(owner, UUID(step["step_id"]))
    course_draft = await services.get_course_draft.execute(owner, course.id)
    pending = await services.get_pending_changes.execute(owner, course.id)
    assert text["blocks"] == 1 and quiz["blocks"] == 2
    assert question["question_id"] == draft.content.blocks[1].questions[0].id
    assert draft.updated_via == "mcp" and draft.status == "new"
    assert [(s.title, s.badge) for s in course_draft.outline[0].steps] == [
        ("Rules", "mcp")
    ]
    assert [(s.step_id, s.via_mcp) for s in pending.steps] == [
        (UUID(step["step_id"]), True)
    ]
    assert course_draft.live_version is None


async def test_mcp_marks_only_what_it_wrote_and_people_can_edit_after_it(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-7: the "via MCP" badge follows the last writer of the step."""
    owner = course.team.owner
    section = await services.draft_commands.create_section(
        owner, course.id, "Limits", via_mcp=True
    )
    step = await services.draft_commands.create_step(
        owner, course.id, section["id"], "Intro", via_mcp=False
    )
    ui_step = await services.get_step_draft.execute(owner, UUID(step["step_id"]))

    await services.draft_commands.add_block(
        owner, ui_step.step_id, text_block("by ai"), via_mcp=True
    )
    after_ai = await services.get_step_draft.execute(owner, ui_step.step_id)
    by_person = await services.save_step_draft.execute(
        owner,
        ui_step.step_id,
        after_ai.content.model_copy(update={"title": "Intro 2"}),
        after_ai.lock_version,
    )

    assert ui_step.updated_via == "ui"
    assert after_ai.updated_via == "mcp"
    assert by_person.updated_via == "ui"


async def test_mcp_never_changes_published_content(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """MCP-6: additions go to the draft; the live version stays as published."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)

    await services.draft_commands.add_block(
        owner, seeded.step_a.step_id, text_block("added by ai"), via_mcp=True
    )

    diff = await services.get_step_diff.execute(owner, seeded.step_a.step_id)
    v1 = await services.get_version.execute(owner, course.id, 1)
    assert len(diff.live.blocks) == 1
    assert len(diff.draft.blocks) == 2
    assert [s.step_id for s in v1.outline[0].steps][0] == seeded.step_a.step_id
    assert (await services.list_versions.execute(owner, course.id))[0].number == 1
    version = await publish(services, owner, course.id)
    assert version.changes.changed == 1


async def test_mcp_commands_need_the_edit_permission(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-22: only staff with `edit` can use the LMS Course MCP to write."""
    owner = course.team.owner
    section = await services.draft_commands.create_section(
        owner, course.id, "Limits", via_mcp=True
    )
    step = await services.draft_commands.create_step(
        owner, course.id, section["id"], "Intro", via_mcp=True
    )

    for actor in (course.team.tester, course.team.reviewer, course.team.outsider):
        with pytest.raises(CoursePermissionError):
            await services.draft_commands.create_section(
                actor, course.id, "Nope", via_mcp=True
            )
        with pytest.raises(CoursePermissionError):
            await services.draft_commands.add_block(
                actor, UUID(step["step_id"]), text_block("Nope"), via_mcp=True
            )


async def test_invalid_blocks_and_questions_are_refused_with_a_typed_error(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The MCP client gets a clear error, not a corrupted draft."""
    owner = course.team.owner
    section = await services.draft_commands.create_section(
        owner, course.id, "Limits", via_mcp=True
    )
    step = UUID(
        (
            await services.draft_commands.create_step(
                owner, course.id, section["id"], "Intro", via_mcp=True
            )
        )["step_id"]
    )
    text = await services.draft_commands.add_block(
        owner, step, text_block("x"), via_mcp=True
    )

    with pytest.raises(ContentInvalidError):
        await services.draft_commands.add_block(
            owner, step, {"type": "audio", "url": "x"}, via_mcp=True
        )
    with pytest.raises(ContentInvalidError):
        await services.draft_commands.add_question(
            owner, step, text["block_id"], single_question(), via_mcp=True
        )
    with pytest.raises(ContentInvalidError):
        await services.draft_commands.add_question(
            owner, step, "missing", single_question(), via_mcp=True
        )
    unchanged = await services.get_step_draft.execute(owner, step)
    assert len(unchanged.content.blocks) == 1


async def test_a_version_conflict_with_a_person_is_retried_once_on_the_new_draft(
    services: AuthoringServices,
    course: CourseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UF-LMS-16 3a: MCP retries on the new draft; nothing of either side is lost."""
    owner, teacher = course.team.owner, course.team.teacher
    section = await services.draft_commands.create_section(
        owner, course.id, "Limits", via_mcp=True
    )
    created = await services.draft_commands.create_step(
        owner, course.id, section["id"], "Intro", via_mcp=True
    )
    step_id = UUID(created["step_id"])
    reads = services.get_step_draft
    original = reads.execute
    calls = {"n": 0}

    async def read_then_let_a_person_save(actor: Actor, sid: UUID) -> StepDraftView:
        view = await original(actor, sid)
        calls["n"] += 1
        if calls["n"] == 1:
            await services.save_step_draft.execute(
                teacher,
                sid,
                content_of("Intro", text_block("by a person")),
                view.lock_version,
            )
        return view

    monkeypatch.setattr(reads, "execute", read_then_let_a_person_save)

    await services.draft_commands.add_block(
        owner, step_id, text_block("by ai"), via_mcp=True
    )

    final = await original(owner, step_id)
    assert calls["n"] == 2
    assert [b.markdown for b in final.content.blocks] == ["by a person", "by ai"]


async def test_queries_return_json_compatible_dicts(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """MCP read tools: course, step, pending, versions are plain JSON."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    queries = services.queries

    detail = await queries.course_detail(course.id, owner)
    step = await queries.step_draft(seeded.step_a.step_id, owner)
    pending = await queries.pending_changes(course.id, owner)
    versions = await queries.versions(course.id, owner)

    for payload in (detail, step, pending, versions):
        json.dumps(payload)
    assert detail["live_version"] == 1 and detail["slug"] == "calculus"
    assert step["content"]["title"] == "Step A"
    assert pending["steps"] == []
    assert versions[0]["number"] == 1


async def test_attempts_query_needs_review_and_reads_the_attempts_table(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """LMS-20: reviewers read recent attempts; testers do not."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    live_revision = (
        await step_row(sessionmaker_in_tx, seeded.step_b.step_id)
    ).live_revision_id
    student = new_id()
    async with sessionmaker_in_tx() as session:
        session.add(
            AttemptRow(
                user_id=student,
                step_id=seeded.step_b.step_id,
                revision_id=live_revision,
                block_id="b",
                attempt_no=1,
                variant={},
                max_score=2,
                score=1,
                passed=False,
            )
        )
        await session.commit()

    attempts = await services.queries.attempts(course.id, course.team.reviewer, 10)

    assert [(a["user_id"], a["score"], a["max_score"]) for a in attempts] == [
        (str(student), 1.0, 2.0)
    ]
    json.dumps(attempts)
    with pytest.raises(CoursePermissionError):
        await services.queries.attempts(course.id, course.team.tester)


def test_the_mcp_contract_has_no_edit_delete_or_publish_methods(
    services: AuthoringServices,
) -> None:
    """MCP-6: course CRUD on drafts is there, but nothing publishes or approves."""
    names = {n for n in dir(services.draft_commands) if not n.startswith("_")}

    assert names == {
        *("create_course", "update_course", "delete_course"),
        *("create_section", "update_module", "delete_module"),
        *("create_step", "update_step", "delete_step"),
        *("add_block", "add_question"),
    }
    assert not [n for n in names if "publish" in n or "approve" in n]


async def test_mcp_tools_send_empty_ids_for_new_things_and_the_server_assigns_them(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: `""` means "no ID yet" for blocks, questions, options and cards."""
    owner = course.team.owner
    section = await services.draft_commands.create_section(
        owner, course.id, "Limits", via_mcp=True
    )
    created = await services.draft_commands.create_step(
        owner, course.id, section["id"], "Intro", via_mcp=True
    )
    step = UUID(created["step_id"])
    quiz = {
        "id": "",
        "type": "test",
        "config": {},
        "questions": [
            {
                "id": "",
                "type": "single",
                "prompt": "(x²)′ = ?",
                "options": [
                    {"id": "", "text": "2x", "correct": True},
                    {"id": "", "text": "x"},
                ],
            }
        ],
    }
    cards = {
        "id": "",
        "type": "flashcards",
        "cards": [
            {"id": "", "front": "f1", "back": "b1"},
            {"id": "", "front": "f2", "back": "b2"},
        ],
    }

    first = await services.draft_commands.add_block(owner, step, quiz, via_mcp=True)
    await services.draft_commands.add_block(owner, step, cards, via_mcp=True)
    await services.draft_commands.add_block(
        owner, step, {"id": "", "type": "text", "markdown": "x"}, via_mcp=True
    )
    await services.draft_commands.add_question(
        owner,
        step,
        first["block_id"],
        {
            "id": "",
            "type": "number",
            "prompt": "3+4",
            "answer": {"value": 7, "tolerance": 0},
        },
        via_mcp=True,
    )

    draft = await services.get_step_draft.execute(owner, step)
    raw = draft.content.model_dump(mode="json")
    ids: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            ids.extend([value["id"]] if "id" in value else [])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    assert len(ids) == 3 + 2 + 2 + 2
    assert all(len(i) == 8 for i in ids) and len(set(ids)) == len(ids)
    assert first["block_id"] == draft.content.blocks[0].id
