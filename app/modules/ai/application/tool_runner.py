"""Turns the model's tool calls into stored calls: read tools run, writes wait."""

import json
from datetime import timedelta
from typing import Any, Final

from app.modules.ai.application.tools.base import Tool, ToolContext, WriteTool
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import APPROVAL_TTL_HOURS
from app.modules.ai.domain.errors import ToolArgumentsError, ToolFailedError
from app.modules.ai.domain.tool_call import ToolAccess, ToolCall, ToolStatus
from app.shared.agent_steps import StepKind, StepStatus, record_step
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.ids import new_id

import structlog
from pydantic_core import to_jsonable_python

log = structlog.get_logger(__name__)


def describe_error(exc: BaseError) -> str:
    """Return the error text the model sees in the tool result."""
    if isinstance(exc, ToolFailedError | ToolArgumentsError):
        return exc.support_details
    return f"{exc.code}: {exc.support_details}"


class ToolRunner:
    """Validates, runs or parks the tool calls of one model response."""

    def __init__(self, registry: ToolRegistry, clock: Clock) -> None:
        """Store the tools and the clock (for approval expiry)."""
        self.registry = registry
        self.clock = clock

    async def propose(
        self,
        assistant: Assistant,
        ctx: ToolContext,
        raw_calls: list[dict[str, Any]],
        taken_ids: set[str],
        seen: dict[str, ToolCall] | None = None,
    ) -> list[ToolCall]:
        """Run read calls now; return write calls as `pending_approval`.

        `seen` holds the read calls done earlier in the turn by `call_key`: the same
        tool with the same (or only differently spaced or cased) arguments is not run
        again; its earlier result comes back marked `repeated`.
        """
        calls: list[ToolCall] = []
        for raw in raw_calls:
            call_id = _unique_id(str(raw.get("id") or ""), taken_ids)
            key = call_key(raw)
            earlier = seen.get(key) if seen is not None else None
            if earlier is not None:
                calls.append(_repeated(earlier, call_id))
                continue
            call = await self._one(assistant, ctx, raw, call_id)
            _record(call)
            calls.append(call)
            done = call.status is ToolStatus.DONE and call.access is ToolAccess.READ
            if seen is not None and done:
                seen[key] = call
        return calls

    async def _one(
        self, assistant: Assistant, ctx: ToolContext, raw: dict[str, Any], call_id: str
    ) -> ToolCall:
        name = str(raw.get("name", ""))
        arguments = raw.get("arguments")
        args: dict[str, Any] = arguments if isinstance(arguments, dict) else {}
        tool = self.registry.get(assistant, name)
        if tool is None:
            return _failed(call_id, name, ToolAccess.READ, args, "unknown tool")
        if raw.get("error"):
            return _failed(call_id, name, tool.access, args, str(raw["error"]))
        try:
            return await self._dispatch(tool, ctx, call_id, args)
        except BaseError as exc:
            return _failed(call_id, name, tool.access, args, describe_error(exc))
        except Exception:  # one broken tool must not abort the whole turn
            log.exception("ai.tool_crashed", tool=name)
            return _failed(call_id, name, tool.access, args, "the tool crashed")

    async def _dispatch(
        self, tool: Tool, ctx: ToolContext, call_id: str, args: dict[str, Any]
    ) -> ToolCall:
        parsed = tool.parse(args)
        await tool.validate(parsed, ctx)
        if isinstance(tool, WriteTool) and await tool.needs_approval(ctx):
            expires = self.clock.now() + timedelta(hours=APPROVAL_TTL_HOURS)
            return ToolCall(
                id=call_id,
                tool=tool.name,
                access=ToolAccess.WRITE,
                args=args,
                status=ToolStatus.PENDING_APPROVAL,
                preview=await tool.preview(parsed, ctx),
                expires_at=expires,
            )
        result = await tool.run(parsed, ctx)
        return ToolCall(
            id=call_id,
            tool=tool.name,
            access=ToolAccess.READ,
            args=args,
            status=ToolStatus.DONE,
            result=to_jsonable_python(result),
        )

    async def run_approved(
        self, assistant: Assistant, ctx: ToolContext, call: ToolCall
    ) -> ToolCall:
        """Re-validate and run an approved call; return it as done or failed."""
        tool = self.registry.get(assistant, call.tool)
        if tool is None:
            return _finish(call, error="unknown tool")
        try:
            parsed = tool.parse(call.args)
            await tool.validate(parsed, ctx)
            result = await tool.run(parsed, ctx)
        except BaseError as exc:
            return _finish(call, error=describe_error(exc))
        except Exception:  # the approved action failed; tell the model, keep the chat
            log.exception("ai.approved_tool_crashed", tool=call.tool)
            return _finish(call, error="the tool crashed")
        return _finish(call, result=to_jsonable_python(result))


_KIND_PREFIXES: Final = (
    ("read_", StepKind.READ_FILE),
    ("search_", StepKind.RETRIEVE),
    ("create_", StepKind.CREATE),
    ("make_", StepKind.CREATE),
    ("add_", StepKind.CREATE),
    ("generate_", StepKind.CREATE),
    ("apply_", StepKind.CREATE),
)


def step_kind_for(tool: str) -> StepKind:
    """The step kind of a tool, read from its name (`read_file` reads a file)."""
    return next((k for p, k in _KIND_PREFIXES if tool.startswith(p)), StepKind.TOOL)


def _record(call: ToolCall) -> None:
    """Record a run or failed call as a step (a parked write shows its own card)."""
    if call.status is ToolStatus.PENDING_APPROVAL:
        return
    result = call.result if isinstance(call.result, dict) else {}
    target = result.get("name") or result.get("title")
    failed = call.status is ToolStatus.FAILED
    record_step(
        step_kind_for(call.tool),
        call.tool,
        target=target if isinstance(target, str) else None,
        ref=call.id,
        status=StepStatus.FAILED if failed else StepStatus.DONE,
    )


def call_key(raw: dict[str, Any]) -> str:
    """The identity of a call within a turn: its tool and normalised arguments."""
    arguments = raw.get("arguments")
    args = arguments if isinstance(arguments, dict) else {}
    return json.dumps(
        [str(raw.get("name", "")), _normalised(args)],
        ensure_ascii=False,
        sort_keys=True,
    )


def _normalised(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, dict):
        return {k: _normalised(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalised(v) for v in value]
    return value


def _repeated(earlier: ToolCall, call_id: str) -> ToolCall:
    """A repeated call: the earlier result, marked so the model stops asking."""
    result = {
        "repeated": "Same call as earlier in this answer; use this result.",
        **(earlier.result or {}),
    }
    return earlier.model_copy(update={"id": call_id, "result": result})


def _unique_id(model_id: str, taken: set[str]) -> str:
    call_id = model_id
    if not call_id or call_id in taken:
        call_id = f"call_{new_id().hex[-12:]}"
    taken.add(call_id)
    return call_id


def _failed(
    call_id: str, name: str, access: ToolAccess, args: dict[str, Any], error: str
) -> ToolCall:
    return ToolCall(
        id=call_id,
        tool=name,
        access=access,
        args=args,
        status=ToolStatus.FAILED,
        error=error,
    )


def _finish(
    call: ToolCall, *, result: dict[str, Any] | None = None, error: str | None = None
) -> ToolCall:
    status = ToolStatus.FAILED if error is not None else ToolStatus.DONE
    return call.model_copy(update={"status": status, "result": result, "error": error})
