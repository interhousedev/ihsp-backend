"""Use case: AI request, spend and daily analytics (admin only, read-only)."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.ai.ports.analytics import (
    AiAnalyticsReader,
    RequestGroup,
    RequestStatsRow,
    SpendDailyRow,
    SpendGroup,
    SpendRow,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory

TASHKENT = ZoneInfo("Asia/Tashkent")
MAX_RANGE_DAYS = 400
DEFAULT_RANGE_DAYS = 30


class AiRangeTooLargeError(ValidationFailedError):
    """The range is backwards or longer than the analytics allow."""

    code = "range_too_large"
    message_key = "ai-analytics-range-too-large"


class AiAnalytics:
    """Serves the analytics endpoints and the MCP tools from the ledger reader."""

    def __init__(
        self,
        *,
        reader: AiAnalyticsReader,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Keep the reader, the directory of names and the clock."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    def _range(self, start: date | None, end: date | None) -> tuple[date, date]:
        last = end or local_today(self.clock)
        first = start or last - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        if first > last or (last - first).days >= MAX_RANGE_DAYS:
            raise AiRangeTooLargeError(params={"max_days": MAX_RANGE_DAYS})
        return first, last

    async def request_stats(
        self,
        actor: Actor,
        *,
        start: date | None = None,
        end: date | None = None,
        request_id: str | None = None,
        pipeline: str | None = None,
        user_id: UUID | None = None,
        group_by: RequestGroup = "request",
    ) -> dict[str, Any]:
        """Averages, totals and cost per group of the requests in range."""
        actor.require(Role.ADMIN)
        first, last = self._range(start, end)
        rows = await self.reader.request_stats(
            first, last, request_id, pipeline, user_id, group_by
        )
        return {
            "items": [_request_item(row) for row in rows],
            "totals": _totals(rows),
        }

    async def spend(
        self,
        actor: Actor,
        *,
        start: date | None = None,
        end: date | None = None,
        by: SpendGroup = "day",
        request_id: str | None = None,
        user_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Spend per day, request or user; the user is named when grouped by user."""
        actor.require(Role.ADMIN)
        first, last = self._range(start, end)
        rows = await self.reader.spend(first, last, by, request_id, user_id, limit)
        names = await self._names(rows) if by == "user" else {}
        items = [_spend_item(row, names) for row in rows]
        return {
            "items": items,
            "total_cost_micro": sum(item["cost_micro"] for item in items),
        }

    async def spend_daily(
        self,
        actor: Actor,
        *,
        start: date | None = None,
        end: date | None = None,
        request_id: str | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Spend per day and request, the twenty costliest requests and the rest."""
        actor.require(Role.ADMIN)
        first, last = self._range(start, end)
        rows = await self.reader.spend_daily(first, last, request_id, user_id)
        return {"items": [_daily_item(row) for row in rows]}

    async def _names(self, rows: list[SpendRow]) -> dict[UUID, dict[str, Any]]:
        ids = [row.user_id for row in rows if row.user_id is not None]
        if not ids:
            return {}
        users = await self.identity.get_users(ids)
        return {
            uid: {
                "id": str(uid),
                "full_name": f"{user.first_name} {user.last_name}".strip(),
                "role": _primary_role(user.roles),
            }
            for uid, user in users.items()
        }


def _request_item(row: RequestStatsRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "calls": row.calls,
        "failed": row.failed,
        "avg_prompt_tokens": row.avg_prompt_tokens,
        "avg_prompt_chars": row.avg_prompt_chars,
        "avg_answer_chars": row.avg_answer_chars,
        "avg_output_tokens": row.avg_output_tokens,
        "avg_tool_calls": row.avg_tool_calls,
        "cost_micro": row.cost_micro,
    }


def _totals(rows: list[RequestStatsRow]) -> dict[str, Any]:
    calls = sum(row.calls for row in rows)
    if not calls:
        return {
            "calls": 0,
            "failed": 0,
            "avg_prompt_tokens": 0.0,
            "avg_prompt_chars": 0.0,
            "avg_answer_chars": 0.0,
            "avg_output_tokens": 0.0,
            "avg_tool_calls": 0.0,
            "cost_micro": 0,
        }
    weighted = {
        name: sum(getattr(row, f"avg_{name}") * row.calls for row in rows) / calls
        for name in (
            "prompt_tokens",
            "prompt_chars",
            "answer_chars",
            "output_tokens",
            "tool_calls",
        )
    }
    return {
        "calls": calls,
        "failed": sum(row.failed for row in rows),
        "avg_prompt_tokens": weighted["prompt_tokens"],
        "avg_prompt_chars": weighted["prompt_chars"],
        "avg_answer_chars": weighted["answer_chars"],
        "avg_output_tokens": weighted["output_tokens"],
        "avg_tool_calls": weighted["tool_calls"],
        "cost_micro": sum(row.cost_micro for row in rows),
    }


def _spend_item(row: SpendRow, names: dict[UUID, dict[str, Any]]) -> dict[str, Any]:
    user = names.get(row.user_id) if row.user_id is not None else None
    return {
        "key": row.key,
        "cost_micro": row.cost_micro,
        "calls": row.calls,
        "users": row.users,
        "user": user,
    }


def _daily_item(row: SpendDailyRow) -> dict[str, Any]:
    return {
        "day": row.day,
        "request_id": row.request_id,
        "cost_micro": row.cost_micro,
        "calls": row.calls,
    }


def _primary_role(roles: frozenset[Role]) -> str | None:
    names = sorted(role.value for role in roles)
    return names[0] if names else None
