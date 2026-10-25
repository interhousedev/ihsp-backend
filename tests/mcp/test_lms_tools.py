"""MCP-6, UF-LMS-16, LMS-22: the LMS Course server reads, and only adds to drafts."""

from uuid import UUID

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

ALL = SCOPES_BY_SERVER["lms"]
COURSE_A = UUID(int=0xA)
COURSE_B = UUID(int=0xB)
STEP_A = UUID(int=0x1A)
STEP_B = UUID(int=0x1B)


def _steps(world: World) -> None:
    world.lms_queries.steps[STEP_A] = {
        "step_id": str(STEP_A),
        "course_id": str(COURSE_A),
    }
    world.lms_queries.steps[STEP_B] = {
        "step_id": str(STEP_B),
        "course_id": str(COURSE_B),
    }


async def test_add_text_block_lands_as_an_mcp_draft_change(world: World) -> None:
    """UF-LMS-16 step 2: the block is appended with via_mcp=True and no id of ours."""
    token, actor = world.connector_token("lms", *ALL)

    async with world.session("lms", token) as session:
        result = await call(
            session, "add_text_block", step_id=str(STEP_A), markdown="# Derivatives"
        )

    assert not result.isError
    [recorded] = world.lms_commands.calls
    assert recorded.name == "add_block"
    assert recorded.via_mcp is True
    assert recorded.actor == actor
    assert recorded.args == (
        STEP_A,
        {"id": "", "type": "text", "markdown": "# Derivatives"},
    )


async def test_section_and_step_are_created_via_mcp(world: World) -> None:
    """UF-LMS-16: create_section and create_step are add-only draft commands."""
    token, actor = world.connector_token("lms", *ALL)

    async with world.session("lms", token) as session:
        section = await call(
            session, "create_section", course_id=str(COURSE_A), title="Derivatives"
        )
        step = await call(
            session,
            "create_step",
            course_id=str(COURSE_A),
            section_id="s1",
            title="Definition",
        )

    assert data_of(section)["title"] == "Derivatives"
    assert data_of(step)["title"] == "Definition"
    assert [c.name for c in world.lms_commands.calls] == [
        "create_section",
        "create_step",
    ]
    assert all(c.via_mcp and c.actor == actor for c in world.lms_commands.calls)
    assert world.lms_commands.calls[0].args == (COURSE_A, "Derivatives")
    assert world.lms_commands.calls[1].args == (COURSE_A, "s1", "Definition")


async def test_add_test_block_builds_config_defaults_and_questions(
    world: World,
) -> None:
    """LMS-15, LMS-16: a test block with settings and mixed questions."""
    token, _ = world.connector_token("lms", *ALL)
    questions = [
        {
            "type": "single",
            "prompt": "2+2?",
            "options": [
                {"text": "4", "correct": True},
                {"text": "None", "pinned": True},
            ],
        },
        {
            "type": "text",
            "prompt": "Capital of Uzbekistan?",
            "accepted_answers": ["Tashkent"],
        },
        {
            "type": "number",
            "prompt": "Pi?",
            "number": 3.14,
            "tolerance": 0.01,
            "points": 2,
        },
    ]

    async with world.session("lms", token) as session:
        result = await call(
            session,
            "add_test_block",
            step_id=str(STEP_A),
            questions=questions,
            settings={"passing_score_pct": 70, "max_attempts": 3},
        )

    assert not result.isError, text_of(result)
    [recorded] = world.lms_commands.calls
    block = recorded.args[1]
    assert block["type"] == "test"
    assert block["config"]["passing_score_pct"] == 70
    assert block["config"]["max_attempts"] == 3
    assert block["config"]["show_answers"] == "after_submit"
    single, text, number = block["questions"]
    assert single["options"][1] == {
        "id": "",
        "text": "None",
        "correct": False,
        "pinned": True,
    }
    assert text["answer"] == {
        "accepted": ["Tashkent"],
        "regex": None,
        "case_sensitive": False,
    }
    assert number["answer"] == {"value": 3.14, "tolerance": 0.01}
    assert number["points"] == 2


async def test_add_question_goes_to_an_existing_test_block(world: World) -> None:
    """UF-LMS-16: add_question appends to a block, never edits others."""
    token, _ = world.connector_token("lms", *ALL)
    question = {
        "type": "multiple",
        "prompt": "Primes?",
        "options": [
            {"text": "2", "correct": True},
            {"text": "3", "correct": True},
            {"text": "4"},
        ],
    }

    async with world.session("lms", token) as session:
        result = await call(
            session,
            "add_question",
            step_id=str(STEP_A),
            block_id="blk1",
            question=question,
        )

    assert not result.isError, text_of(result)
    [recorded] = world.lms_commands.calls
    assert recorded.name == "add_question"
    assert recorded.args[:2] == (STEP_A, "blk1")
    assert recorded.args[2]["type"] == "multiple"
    assert recorded.via_mcp is True


async def test_invalid_questions_are_refused_before_the_use_case(world: World) -> None:
    """Single choice with two correct options; text and number without answers."""
    token, _ = world.connector_token("lms", *ALL)
    two_correct = {
        "type": "single",
        "prompt": "q",
        "options": [{"text": "a", "correct": True}, {"text": "b", "correct": True}],
    }

    async with world.session("lms", token) as session:
        first = await call(
            session,
            "add_question",
            step_id=str(STEP_A),
            block_id="b",
            question=two_correct,
        )
        second = await call(
            session,
            "add_question",
            step_id=str(STEP_A),
            block_id="b",
            question={"type": "text", "prompt": "q"},
        )
        third = await call(
            session,
            "add_question",
            step_id=str(STEP_A),
            block_id="b",
            question={"type": "number", "prompt": "q"},
        )

    assert "exactly one correct option" in text_of(first)
    assert "accepted_answers or a regex" in text_of(second)
    assert "needs the right value" in text_of(third)
    assert world.lms_commands.calls == []


async def test_add_flashcards_block_uses_course_cards(world: World) -> None:
    """LMS-18: a flash cards block with its own cards."""
    token, _ = world.connector_token("lms", *ALL)

    async with world.session("lms", token) as session:
        await call(
            session,
            "add_flashcards_block",
            step_id=str(STEP_A),
            cards=[{"front": "f", "back": "b"}],
        )

    [recorded] = world.lms_commands.calls
    assert recorded.args[1] == {
        "id": "",
        "type": "flashcards",
        "cards": [{"id": "", "front": "f", "back": "b"}],
    }


async def test_read_tools_ask_the_use_cases_as_the_caller(world: World) -> None:
    """MCP-8: read tools pass the actor so edit permission is checked at call time."""
    token, actor = world.connector_token("lms", *ALL)
    world.lms_queries.courses = [{"id": str(COURSE_A), "title": "Calculus"}]
    _steps(world)

    async with world.session("lms", token) as session:
        courses = await call(session, "list_courses")
        course = await call(session, "get_course", course_id=str(COURSE_A))
        step = await call(session, "get_step", step_id=str(STEP_A))
        pending = await call(session, "list_pending_changes", course_id=str(COURSE_A))
        versions = await call(session, "list_versions", course_id=str(COURSE_A))
        attempts = await call(
            session, "list_attempts", course_id=str(COURSE_A), limit=5
        )

    assert data_of(courses)["courses"][0]["title"] == "Calculus"
    assert data_of(course)["title"] == "Calculus"
    assert data_of(step)["course_id"] == str(COURSE_A)
    assert data_of(pending)["draft_seq"] == 4
    assert data_of(versions)["versions"] == [{"number": 1}]
    assert data_of(attempts)["attempts"] == [{"id": "a1"}]
    names = [name for name, _ in world.lms_queries.calls]
    assert names == [
        "courses_for_staff",
        "course_detail",
        "step_draft",
        "pending_changes",
        "versions",
        "attempts",
    ]
    assert world.lms_queries.calls[0][1] == (actor.user_id, "edit")
    assert world.lms_queries.calls[5][1] == (COURSE_A, 5)


async def test_connector_limited_to_courses_sees_only_those(world: World) -> None:
    """MCP-2, MCP-5: `course:<id>` scopes limit list, read and write tools."""
    token, _ = world.connector_token("lms", *ALL, f"course:{COURSE_A}")
    world.lms_queries.courses = [{"id": str(COURSE_A)}, {"id": str(COURSE_B)}]
    _steps(world)

    async with world.session("lms", token) as session:
        listed = await call(session, "list_courses")
        own_course = await call(session, "get_course", course_id=str(COURSE_A))
        other_course = await call(session, "get_course", course_id=str(COURSE_B))
        other_step = await call(session, "get_step", step_id=str(STEP_B))
        own_write = await call(
            session, "add_text_block", step_id=str(STEP_A), markdown="x"
        )
        other_write = await call(
            session, "add_text_block", step_id=str(STEP_B), markdown="x"
        )
        other_section = await call(
            session, "create_section", course_id=str(COURSE_B), title="x"
        )

    assert data_of(listed)["courses"] == [{"id": str(COURSE_A)}]
    assert not own_course.isError
    assert "limited to other courses" in text_of(other_course)
    assert other_step.isError
    assert not own_write.isError
    assert other_write.isError
    assert other_section.isError
    assert [c.args[0] for c in world.lms_commands.calls] == [STEP_A]
    denied = world.audit.of_type("mcp.denied")
    assert {e.metadata["reason"] for e in denied if e.metadata} == {
        "mcp/course-not-allowed"
    }
    assert len(denied) == 4


async def test_course_restriction_can_come_from_the_connector_port(
    world: World,
) -> None:
    """MCP-2: without scope markers the optional port answers for the connector."""
    token, actor = world.connector_token("lms", *ALL)
    assert actor.connector_id is not None
    world.connector_courses.by_connector[actor.connector_id] = frozenset({COURSE_A})

    async with world.session("lms", token, with_course_port=True) as session:
        allowed = await call(session, "get_course", course_id=str(COURSE_A))
        refused = await call(session, "get_course", course_id=str(COURSE_B))

    assert not allowed.isError
    assert refused.isError


async def test_oauth_user_without_restriction_reaches_every_course(
    world: World,
) -> None:
    """MCP-2: no restriction means every course the user can edit."""
    token, _ = world.connector_token("lms", *ALL)

    async with world.session("lms", token, with_course_port=True) as session:
        result = await call(session, "get_course", course_id=str(COURSE_B))

    assert not result.isError


async def test_version_conflict_is_reported_to_the_client(world: World) -> None:
    """UF-LMS-16 3a: a conflict becomes a tool error the client can retry."""
    from app.shared.base_error import ConflictError

    token, _ = world.connector_token("lms", *ALL)

    async def conflicting(*args: object, **kwargs: object) -> dict[str, object]:
        raise ConflictError(support_details="lock version changed")

    world.lms_commands.add_block = conflicting  # type: ignore[method-assign]

    async with world.session("lms", token) as session:
        result = await call(
            session, "add_text_block", step_id=str(STEP_A), markdown="x"
        )

    assert result.isError
