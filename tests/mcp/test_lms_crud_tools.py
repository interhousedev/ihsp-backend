"""MCP course, module and step CRUD, and the scopes that gate each tool."""

from uuid import UUID

from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

COURSE = UUID(int=0xA)
STEP = UUID(int=0x1A)

READ = "lms.courses.read"
WRITE = "lms.courses.write"
DELETE = "lms.courses.delete"
MODULES = "lms.modules.write"


async def test_course_create_update_delete_over_mcp(world: World) -> None:
    """create_course, update_course and delete_course reach the LMS as this actor."""
    token, actor = world.connector_token("lms", READ, WRITE, DELETE)

    async with world.session("lms", token) as session:
        created = await call(session, "create_course", title="Algebra")
        updated = await call(
            session, "update_course", course_id=str(COURSE), title="Algebra 2"
        )
        deleted = await call(session, "delete_course", course_id=str(COURSE))

    for result in (created, updated, deleted):
        assert not result.isError, text_of(result)
    assert data_of(deleted)["status"] == "archived"
    assert [c.name for c in world.lms_commands.calls] == [
        "create_course",
        "update_course",
        "delete_course",
    ]
    assert world.lms_commands.calls[0].args == ("Algebra", None, "invite")
    assert all(c.actor == actor for c in world.lms_commands.calls)


async def test_modules_scope_edits_modules_and_steps_but_not_the_course(
    world: World,
) -> None:
    """A client granted only lms.modules.write cannot touch the course itself."""
    token, _ = world.connector_token("lms", MODULES)

    async with world.session("lms", token) as session:
        module = await call(
            session, "create_module", course_id=str(COURSE), title="Limits"
        )
        renamed = await call(
            session,
            "update_module",
            course_id=str(COURSE),
            module_id="s1",
            title="Limits 2",
        )
        step = await call(
            session,
            "update_step",
            step_id=str(STEP),
            title="Epsilon",
            blocks=[{"type": "text", "markdown": "hi"}],
        )
        removed = await call(session, "delete_step", step_id=str(STEP))
        gone = await call(
            session, "delete_module", course_id=str(COURSE), module_id="s1"
        )
        title = await call(
            session, "update_course", course_id=str(COURSE), title="Hacked"
        )
        delete = await call(session, "delete_course", course_id=str(COURSE))
        create = await call(session, "create_course", title="New")

    for ok in (module, renamed, step, removed, gone):
        assert not ok.isError, text_of(ok)
    for refused, scope in ((title, WRITE), (delete, DELETE), (create, WRITE)):
        assert refused.isError
        assert "insufficient_scope" in text_of(refused)
        assert scope in text_of(refused)
    names = [c.name for c in world.lms_commands.calls]
    assert "update_course" not in names and "delete_course" not in names
    update = next(c for c in world.lms_commands.calls if c.name == "update_step")
    blocks = update.args[2]
    assert blocks == [{"id": "", "type": "text", "markdown": "hi"}]


async def test_the_pre_split_scopes_keep_their_meaning(world: World) -> None:
    """A connector made with courses:draft may still edit modules, nothing more."""
    token, _ = world.connector_token("lms", "courses:read", "courses:draft")

    async with world.session("lms", token) as session:
        ok = await call(session, "create_module", course_id=str(COURSE), title="m")
        refused = await call(session, "update_course", course_id=str(COURSE), title="x")

    assert not ok.isError, text_of(ok)
    assert refused.isError
