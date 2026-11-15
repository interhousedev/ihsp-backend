"""Maintenance mode: MCP writes are refused, reads keep working."""

from app.shared.maintenance import MaintenanceInfo
from tests.mcp.conftest import World
from tests.mcp.helpers import call, text_of


class Gate:
    """A maintenance gate with a fixed state."""

    def __init__(self, active: bool) -> None:
        self.active = active

    def info(self) -> MaintenanceInfo:
        return MaintenanceInfo(active=self.active)


async def test_a_write_tool_is_refused_and_a_read_tool_works(world: World) -> None:
    """create_flashcard_set is refused with the localized notice; list works."""
    world.maintenance = Gate(True)
    token, _ = world.connector_token("student", "flashcards:write", "flashcards:read")
    async with world.session("student", token) as session:
        refused = await call(
            session,
            "create_flashcard_set",
            title="T",
            cards=[{"front": "f", "back": "b"}],
        )
        listed = await call(session, "list_flashcard_sets")

    assert refused.isError
    assert world.i18n.t("en", "error-maintenance") in text_of(refused)
    assert not world.flashcards.sets
    assert not listed.isError


async def test_a_write_tool_works_when_maintenance_is_off(world: World) -> None:
    """The same write passes when the gate is inactive."""
    world.maintenance = Gate(False)
    token, _ = world.connector_token("student", "flashcards:write")
    async with world.session("student", token) as session:
        result = await call(
            session,
            "create_flashcard_set",
            title="T",
            cards=[{"front": "f", "back": "b"}],
        )

    assert not result.isError, text_of(result)
