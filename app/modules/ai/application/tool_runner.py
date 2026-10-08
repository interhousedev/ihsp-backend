"""Turns the model's tool calls into stored calls: read tools run, writes wait."""

from datetime import timedelta
from typing import Any

from app.modules.ai.application.tools.base import Tool, ToolContext, WriteTool
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import APPROVAL_TTL_HOURS
from app.modules.ai.domain.errors import ToolArgumentsError, ToolFailedError
from app.modules.ai.domain.tool_call import ToolAccess, ToolCall, ToolStatus
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
    ) -> list[ToolCall]:
        """Run read calls now; return write calls as `pending_approval`."""
        calls: list[ToolCall] = []
        for raw in raw_calls:
            call_id = _unique_id(str(raw.get("id") or ""), taken_ids)
            calls.append(await self._one(assistant, ctx, raw, call_id))
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
        if isinstance(tool, WriteTool):
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
