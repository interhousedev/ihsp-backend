"""B1: the call log stores an allow-listed trace of every tool call, never content."""

import json
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.call_log import (
    LogSpec,
    check_log_spec,
    redact_arguments,
    summarize_result,
)
from app.interfaces.mcp.errors import McpInvalidInputError, McpNotFoundError
from app.interfaces.mcp.guard import ToolGuard
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

ID = UUID(int=7)


class Kind(StrEnum):
    A = "a"


def test_kept_fields_stay_and_every_other_string_only_has_a_length() -> None:
    """B1: default deny; a short query cannot be guessed from a hash."""
    stored = redact_arguments(
        {"subject_id": ID, "day": date(2026, 1, 2), "n": 3, "query": "my secret"},
        LogSpec(keep=("subject_id", "day", "n")),
    )

    assert stored == {
        "subject_id": str(ID),
        "day": "2026-01-02",
        "n": 3,
        "query": {"len": 9},
    }


def test_lists_are_counted_and_other_values_are_only_present() -> None:
    """B1: card text and question text are never stored, even if listed in keep."""
    stored = redact_arguments(
        {"cards": [{"front": "secret"}], "flag": True, "skipped": None},
        LogSpec(keep=("cards",)),
    )

    assert stored == {"cards": {"count": 1}, "flag": {"present": True}}


def test_a_tool_without_a_spec_logs_only_its_name() -> None:
    """B1: no spec, no arguments."""
    assert redact_arguments({"subject_id": ID}, None) is None
    assert summarize_result({"count": 1}, None) is None


def test_result_summary_keeps_counts_and_ids_only() -> None:
    """B1: never content, marks or GPA, whatever a summarize function returns."""
    spec = LogSpec(
        summarize=lambda result: {
            "count": result["count"],
            "id": result["id"],
            "status": "ready",
            "gpa": 4.5,
            "text": "Some Free Text",
            "ids": [result["id"]],
            "nested": {"a": 1},
        }
    )

    summary = summarize_result({"count": 2, "id": str(ID)}, spec)

    assert summary == {
        "count": 2,
        "id": str(ID),
        "status": "ready",
        "ids": [str(ID)],
    }


def test_a_broken_summarize_function_stores_nothing_and_does_not_raise() -> None:
    """B1: logging never fails a call."""
    spec = LogSpec(summarize=lambda result: result["missing"])

    assert summarize_result({}, spec) is None


def test_keep_accepts_ids_dates_numbers_booleans_and_enums() -> None:
    """B1: a typed parameter may be kept."""

    def tool(
        a: Annotated[UUID, Field(description="x")],
        b: date | None,
        c: int,
        d: bool,
        e: Kind,
        f: Literal["x", "y"] | None,
    ) -> None:
        return None

    check_log_spec("tool", tool, LogSpec(keep=("a", "b", "c", "d", "e", "f")))


@pytest.mark.parametrize("name", ["query", "payload", "missing"])
def test_keep_refuses_free_text_and_unknown_parameters_at_registration(
    name: str,
) -> None:
    """B1: a query can never be allow-listed by mistake."""

    def tool(query: str, payload: dict[str, Any]) -> None:
        return None

    with pytest.raises(ValueError, match=name):
        check_log_spec("tool", tool, LogSpec(keep=(name,)))


async def test_a_successful_call_writes_one_row_without_content(world: World) -> None:
    """B1: names, ids and timing are stored; card text is not."""
    token, actor = world.connector_token("student", "flashcards:write")

    async with world.session("student", token) as session:
        result = await call(
            session,
            "create_flashcard_set",
            title="Private title",
            cards=[{"front": "Private front", "back": "Private back"}],
        )
    data_of(result)

    [row] = world.call_log.records
    assert row.user_id == actor.user_id
    assert row.connector_id == actor.connector_id
    assert (row.server, row.tool) == ("student", "create_flashcard_set")
    assert row.scope == "flashcards:write"
    assert row.read_only is False
    assert row.outcome == "ok"
    assert row.duration_ms >= 0
    assert "Private" not in json.dumps(row.arguments)
    assert "Private" not in json.dumps(row.result_summary)
    assert row.arguments is not None
    assert row.arguments["cards"] == {"count": 1}


async def test_read_tools_without_a_spec_log_only_the_name(world: World) -> None:
    """B1: no spec, no arguments, still one row."""
    token, _ = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        await call(session, "get_my_subjects")

    [row] = world.call_log.records
    assert row.tool == "get_my_subjects"
    assert row.arguments is None


async def test_a_search_query_is_stored_only_as_its_length(world: World) -> None:
    """B1: a kept spec never keeps the free text."""
    token, _ = world.connector_token("student", "files:read")

    async with world.session("student", token) as session:
        await call(session, "search_files", query="Private query")

    [row] = world.call_log.records
    assert row.arguments is not None
    assert row.arguments["query"] == {"len": 13}
    assert "Private" not in str(row)


async def test_a_denied_call_is_logged_with_its_code(world: World) -> None:
    """B1: outcome denied, error code, and the audit event stays."""
    token, _ = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        await call(session, "get_marks")

    [row] = world.call_log.records
    assert row.outcome == "denied"
    assert row.error_code == "mcp/insufficient-scope"
    assert world.audit.of_type("mcp.denied")


async def _run(world: World, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    actor = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
    actor = Actor(
        user_id=actor.user_id,
        roles=actor.roles,
        connector_id=new_id(),
        scopes=frozenset({"marks:read"}),
    )
    monkeypatch.setattr(guard_module, "_token_actor", lambda: actor)

    async def tool() -> dict[str, Any]:
        raise error

    wrapped = ToolGuard(world.deps(), "student").requires_scope("marks:read")(tool)
    with pytest.raises(ToolError):
        await wrapped()


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (McpNotFoundError(), "not_found"),
        (McpInvalidInputError(params={"reason": "x"}), "invalid"),
        (RuntimeError("secret sql"), "error"),
    ],
)
async def test_failures_map_to_outcomes(
    world: World, monkeypatch: pytest.MonkeyPatch, error: Exception, outcome: str
) -> None:
    """B1: one row per outcome."""
    await _run(world, monkeypatch, error)

    [row] = world.call_log.records
    assert row.outcome == outcome
    assert "secret sql" not in str(row)


async def test_an_internal_error_stores_the_id_shown_to_the_client(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1: support can find the row from the message."""
    await _run(world, monkeypatch, RuntimeError("boom"))

    [row] = world.call_log.records
    assert row.error_id


async def test_rate_limited_is_its_own_outcome(world: World) -> None:
    """B1: outcome rate_limited."""
    token, actor = world.connector_token("student", "schedule:read")
    await world.redis.set(f"rl:mcp:{actor.connector_id}", 60, ex=60)

    async with world.session("student", token) as session:
        await call(session, "get_schedule")

    [row] = world.call_log.records
    assert row.outcome == "rate_limited"


async def test_a_failed_log_write_does_not_fail_the_call(world: World) -> None:
    """B1: the student's call matters more than its trace."""
    token, _ = world.connector_token("student", "schedule:read")
    world.call_log.fail = True

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule")

    assert not result.isError


async def test_the_client_address_comes_from_the_trusted_proxy_rule(
    world: World,
) -> None:
    """B1: a client cannot pick the address stored about it."""
    token, _ = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        await call(session, "get_schedule")

    [row] = world.call_log.records
    assert row.ip == "127.0.0.1"
