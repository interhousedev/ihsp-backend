"""ToolRunner: reads run, writes wait, and a crashed tool fails only its own call."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from app.modules.ai.application.tool_runner import ToolRunner, describe_error
from app.modules.ai.application.tools.base import ReadTool, ToolContext, WriteTool
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import APPROVAL_TTL_HOURS
from app.modules.ai.domain.errors import ToolArgumentsError, ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import (
    PreviewData,
    ToolAccess,
    ToolCall,
    ToolStatus,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.fakes.clock import FixedClock

import pytest
import structlog


class EchoArgs(ToolArgs):
    """One required string."""

    text: str


class Echo(ReadTool[EchoArgs]):
    """Returns its argument."""

    name = "echo"
    description = "echo"
    args_model = EchoArgs

    async def run(self, args: EchoArgs, ctx: ToolContext) -> dict[str, Any]:
        return {"text": args.text}


class Crash(ReadTool[EchoArgs]):
    """Raises a non-domain exception."""

    name = "crash"
    description = "crash"
    args_model = EchoArgs

    async def run(self, args: EchoArgs, ctx: ToolContext) -> dict[str, Any]:
        raise RuntimeError("boom")


class Refuse(ReadTool[EchoArgs]):
    """Fails with domain errors from validate or run."""

    name = "refuse"
    description = "refuse"
    args_model = EchoArgs

    async def validate(self, args: EchoArgs, ctx: ToolContext) -> None:
        if args.text == "forbidden":
            raise ForbiddenError(support_details="not yours")

    async def run(self, args: EchoArgs, ctx: ToolContext) -> dict[str, Any]:
        raise ToolFailedError(support_details="nothing found")


class Rename(WriteTool[EchoArgs]):
    """A write tool: parked until approved."""

    name = "rename"
    description = "rename"
    args_model = EchoArgs
    runs = 0

    async def preview(self, args: EchoArgs, ctx: ToolContext) -> PreviewData:
        return PreviewData(title_key="rename", items=[args.text])

    async def run(self, args: EchoArgs, ctx: ToolContext) -> dict[str, Any]:
        Rename.runs += 1
        return {"renamed": args.text}


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def runner(clock: FixedClock) -> ToolRunner:
    registry = ToolRegistry(student=[Echo(), Crash(), Refuse(), Rename()], admin=[])
    return ToolRunner(registry, clock)


@pytest.fixture
def ctx() -> ToolContext:
    actor = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))
    return ToolContext(actor=actor, chat_id=uuid4(), locale="en")


def _raw(name: str, **args: Any) -> dict[str, Any]:
    return {"id": f"call_{name}", "name": name, "arguments": args}


async def test_read_calls_run_and_write_calls_wait(
    runner: ToolRunner, ctx: ToolContext, clock: FixedClock
) -> None:
    """AI-3: reads are done at once; a write is pending with a preview and an expiry."""
    Rename.runs = 0

    calls = await runner.propose(
        Assistant.STUDENT,
        ctx,
        [_raw("echo", text="hi"), _raw("rename", text="x")],
        set(),
    )

    echo, rename = calls
    assert (echo.status, echo.access, echo.result) == (
        ToolStatus.DONE,
        ToolAccess.READ,
        {"text": "hi"},
    )
    assert (rename.status, rename.access) == (
        ToolStatus.PENDING_APPROVAL,
        ToolAccess.WRITE,
    )
    assert rename.preview is not None and rename.preview.items == ["x"]
    assert rename.expires_at == clock.now() + timedelta(hours=APPROVAL_TTL_HOURS)
    assert Rename.runs == 0


async def test_a_crashed_tool_fails_only_its_own_call(
    runner: ToolRunner, ctx: ToolContext
) -> None:
    """One broken tool must not abort the turn; the crash is logged with its name."""
    with structlog.testing.capture_logs() as logs:
        calls = await runner.propose(
            Assistant.STUDENT,
            ctx,
            [_raw("crash", text="a"), _raw("echo", text="b")],
            set(),
        )

    crashed, fine = calls
    assert (crashed.status, crashed.error) == (ToolStatus.FAILED, "the tool crashed")
    assert (fine.status, fine.result) == (ToolStatus.DONE, {"text": "b"})
    assert [(e["event"], e["tool"]) for e in logs] == [("ai.tool_crashed", "crash")]


async def test_domain_errors_become_the_model_facing_text(
    runner: ToolRunner, ctx: ToolContext
) -> None:
    """Bad arguments, a refused validation and a tool failure are all `failed` calls."""
    calls = await runner.propose(
        Assistant.STUDENT,
        ctx,
        [
            _raw("echo"),  # missing `text`
            _raw("refuse", text="forbidden"),
            _raw("refuse", text="ok"),
            _raw("nope", text="x"),
            {"id": "c", "name": "echo", "arguments": {"text": "x"}, "error": "cut"},
        ],
        set(),
    )

    assert [c.status for c in calls] == [ToolStatus.FAILED] * 5
    assert calls[0].error is not None and "text" in calls[0].error
    assert calls[1].error == "common/forbidden: not yours"
    assert calls[2].error == "nothing found"
    assert calls[3].error == "unknown tool"
    assert calls[4].error == "cut"


async def test_call_ids_are_kept_unless_missing_or_taken(
    runner: ToolRunner, ctx: ToolContext
) -> None:
    """Stored calls keep the model's ids; a duplicate or empty id gets a fresh one."""
    taken = {"call_echo"}

    calls = await runner.propose(
        Assistant.STUDENT,
        ctx,
        [_raw("echo", text="a"), {"name": "echo", "arguments": {"text": "b"}}],
        taken,
    )

    assert calls[0].id != "call_echo" and calls[0].id.startswith("call_")
    assert calls[1].id.startswith("call_")
    assert len({calls[0].id, calls[1].id, "call_echo"}) == 3
    assert taken == {"call_echo", calls[0].id, calls[1].id}


async def test_an_approved_write_runs_and_is_finished(
    runner: ToolRunner, ctx: ToolContext
) -> None:
    """AI-11: the approved call is re-validated, run and returned as done."""
    Rename.runs = 0
    pending = ToolCall(
        id="c1",
        tool="rename",
        access=ToolAccess.WRITE,
        args={"text": "x"},
        status=ToolStatus.PENDING_APPROVAL,
    )

    done = await runner.run_approved(Assistant.STUDENT, ctx, pending)

    assert (done.status, done.result, done.error) == (
        ToolStatus.DONE,
        {"renamed": "x"},
        None,
    )
    assert Rename.runs == 1


async def test_an_approved_call_that_crashes_keeps_the_chat(
    runner: ToolRunner, ctx: ToolContext
) -> None:
    """A crash or a removed tool ends as a failed call, never an exception."""
    base = {"access": ToolAccess.READ, "status": ToolStatus.PENDING_APPROVAL}
    crash = ToolCall(id="c1", tool="crash", args={"text": "x"}, **base)
    gone = ToolCall(id="c2", tool="gone", args={}, **base)
    bad = ToolCall(id="c3", tool="echo", args={}, **base)

    with structlog.testing.capture_logs() as logs:
        crashed = await runner.run_approved(Assistant.STUDENT, ctx, crash)
    unknown = await runner.run_approved(Assistant.STUDENT, ctx, gone)
    invalid = await runner.run_approved(Assistant.STUDENT, ctx, bad)

    assert (crashed.status, crashed.error) == (ToolStatus.FAILED, "the tool crashed")
    assert [e["event"] for e in logs] == ["ai.approved_tool_crashed"]
    assert unknown.error == "unknown tool"
    assert invalid.status is ToolStatus.FAILED and invalid.error is not None


def test_describe_error_hides_the_code_for_tool_errors() -> None:
    """The model reads plain text for tool errors and `code: details` otherwise."""
    assert describe_error(ToolFailedError(support_details="no")) == "no"
    assert describe_error(ToolArgumentsError(support_details="bad")) == "bad"
    assert describe_error(ForbiddenError(support_details="x")) == "common/forbidden: x"
