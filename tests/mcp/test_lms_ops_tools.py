"""MCP-6: LMS course operations honour the connector's course limits and scopes."""

from uuid import UUID

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

ALL = SCOPES_BY_SERVER["lms"]
COURSE_A = UUID(int=0xA)
COURSE_B = UUID(int=0xB)
STEP_A = UUID(int=0x1A)
STEP_B = UUID(int=0x1B)
ATTEMPT_A = UUID(int=0x2A)
ATTEMPT_B = UUID(int=0x2B)


def _seed(world: World) -> None:
    for step, course in ((STEP_A, COURSE_A), (STEP_B, COURSE_B)):
        world.lms_queries.steps[step] = {
            "step_id": str(step),
            "course_id": str(course),
        }
    world.lms_ops.attempts[ATTEMPT_A] = {
        "id": str(ATTEMPT_A),
        "course_id": str(COURSE_A),
    }
    world.lms_ops.attempts[ATTEMPT_B] = {
        "id": str(ATTEMPT_B),
        "course_id": str(COURSE_B),
    }


def _ops(world: World, name: str) -> list[tuple[object, ...]]:
    return [c.args for c in world.lms_ops.calls if c.name == name]


async def test_move_section_runs_for_the_allowed_course_only(world: World) -> None:
    """A connector limited to course A moves in A; B is refused untouched."""
    token, actor = world.connector_token("lms", *ALL, f"course:{COURSE_A}")

    async with world.session("lms", token) as session:
        ok = await call(
            session, "move_section", course_id=str(COURSE_A), section_id="s", position=2
        )
        refused = await call(
            session, "move_section", course_id=str(COURSE_B), section_id="s", position=2
        )

    assert not ok.isError
    [recorded] = world.lms_ops.calls
    assert recorded.name == "move_section"
    assert recorded.actor == actor
    assert recorded.args == (COURSE_A, "s", 2)
    assert refused.isError
    assert "limited to other courses" in text_of(refused)


async def test_publish_passes_the_note_and_respects_course_limits(
    world: World,
) -> None:
    """publish forwards the note for course A and never reaches course B."""
    token, actor = world.connector_token("lms", *ALL, f"course:{COURSE_A}")

    async with world.session("lms", token) as session:
        ok = await call(session, "publish", course_id=str(COURSE_A), note="v2")
        refused = await call(session, "publish", course_id=str(COURSE_B))

    assert not ok.isError
    assert _ops(world, "publish") == [(COURSE_A, "v2")]
    assert world.lms_ops.calls[0].actor == actor
    assert refused.isError
    assert "limited to other courses" in text_of(refused)


async def test_block_operations_on_a_foreign_step_are_refused(world: World) -> None:
    """delete_block and move_block look up the step's course first."""
    _seed(world)
    token, _ = world.connector_token("lms", *ALL, f"course:{COURSE_A}")

    async with world.session("lms", token) as session:
        mine = await call(session, "delete_block", step_id=str(STEP_A), block_id="b")
        foreign_delete = await call(
            session, "delete_block", step_id=str(STEP_B), block_id="b"
        )
        foreign_move = await call(
            session, "move_block", step_id=str(STEP_B), block_id="b", position=0
        )

    assert not mine.isError
    assert foreign_delete.isError and foreign_move.isError
    assert "limited to other courses" in text_of(foreign_delete)
    assert _ops(world, "delete_block") == [(STEP_A, "b")]
    assert _ops(world, "move_block") == []


async def test_override_score_checks_the_course_of_the_attempt(world: World) -> None:
    """An attempt of another course is refused; the own one is graded."""
    _seed(world)
    token, actor = world.connector_token("lms", *ALL, f"course:{COURSE_A}")

    async with world.session("lms", token) as session:
        refused = await call(
            session,
            "override_score",
            attempt_id=str(ATTEMPT_B),
            score=9,
            comment="regrade",
        )
        granted = await call(
            session,
            "override_score",
            attempt_id=str(ATTEMPT_A),
            score=7,
            comment="regrade",
        )

    assert refused.isError
    assert "limited to other courses" in text_of(refused)
    assert not granted.isError
    [(_, args)] = [
        (c.actor, c.args) for c in world.lms_ops.calls if c.name == "override_score"
    ]
    assert args == (ATTEMPT_A, 7, "regrade")
    overrides = [c for c in world.lms_ops.calls if c.name == "override_score"]
    assert overrides[0].actor == actor


async def test_get_attempt_of_another_course_is_refused(world: World) -> None:
    """Reading an attempt is limited by its course too."""
    _seed(world)
    token, _ = world.connector_token("lms", *ALL, f"course:{COURSE_A}")

    async with world.session("lms", token) as session:
        refused = await call(session, "get_attempt", attempt_id=str(ATTEMPT_B))
        own = await call(session, "get_attempt", attempt_id=str(ATTEMPT_A))

    assert refused.isError
    assert data_of(own)["course_id"] == str(COURSE_A)


async def test_publish_needs_the_course_write_scope(world: World) -> None:
    """A read-only token cannot publish and the port is not reached."""
    token, _ = world.connector_token("lms", "lms.courses.read")

    async with world.session("lms", token) as session:
        result = await call(session, "publish", course_id=str(COURSE_A))

    assert result.isError
    assert "lms.courses.write" in text_of(result)
    assert world.lms_ops.calls == []


async def test_generate_course_draft_without_ai_explains_itself(world: World) -> None:
    """With no AI wired the tool points the caller to build_course."""
    token, _ = world.connector_token("lms", *ALL)

    async with world.session("lms", token) as session:
        result = await call(session, "generate_course_draft", topic="Algebra")

    assert result.isError
    assert "AI drafting is not available on this server" in text_of(result)
    assert world.lms_ops.calls == []
