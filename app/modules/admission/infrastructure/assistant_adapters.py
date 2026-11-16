"""Adapters of the assistant ports.

The model runs over the notebook LLM, the data over the unit of work. Both only read.
"""

import dataclasses
import datetime as dt
import enum
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.notebooks.application.llm import NotebookLlm
from app.shared.ai_tasks import AiTask


class GatewayAssistantModel:
    """One tool-enabled request through the task's profile."""

    def __init__(self, llm: NotebookLlm) -> None:
        """Keep the client."""
        self._llm = llm

    async def turn(
        self,
        *,
        task: AiTask,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return `{text, tool_calls, usage}` of the gateway result."""
        profile = self._llm.profile(task)
        result = await self._llm.gateway.complete(
            model=profile.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            provider=profile.provider(),
            tuning=profile.tuning,
        )
        return {
            "text": result.get("text", "") or "",
            "tool_calls": list(result.get("tool_calls") or []),
            "usage": result.get("usage", {}),
        }


def _plain(value: Any) -> Any:
    """JSON-safe copy: dates to ISO, UUIDs and decimals to text."""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


_DROP = {"student_id", "id", "lock_version", "created_at", "updated_at"}


def _row(value: Any, keep: tuple[str, ...] = ()) -> dict[str, Any]:
    out = _plain(value)
    return {k: v for k, v in out.items() if k not in _DROP or k in keep}


class UowAssistantData:
    """Reads one student's rows; the caller passes the already checked id."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the transaction factory."""
        self._uow = uow_factory

    async def profile(self, student_id: UUID) -> dict[str, Any]:
        """Stage and answers."""
        async with self._uow() as uow:
            p = await uow.profiles.get(student_id)
        if p is None:
            return {"stage": "setup", "answers": {}}
        return {"stage": p.stage, "answers": _plain(p.answers)}

    async def tasks(self, student_id: UUID) -> list[dict[str, Any]]:
        """Tasks."""
        async with self._uow() as uow:
            rows = await uow.tasks.list_for(student_id)
        return [_row(t, ("id",)) for t in rows]

    async def items(self, student_id: UUID) -> list[dict[str, Any]]:
        """Activities and honors."""
        async with self._uow() as uow:
            rows = await uow.items.list_for(student_id)
        return [_row(i, ("id",)) for i in rows]

    async def test_scores(self, student_id: UUID) -> list[dict[str, Any]]:
        """Test scores."""
        async with self._uow() as uow:
            rows = await uow.test_scores.entries(student_id)
        return [_row(s) for s in rows]

    async def universities(self, student_id: UUID) -> list[dict[str, Any]]:
        """The list with institution names."""
        async with self._uow() as uow:
            entries = await uow.shortlist.entries(student_id)
            names = await uow.deadlines.institution_names(
                {e.institution_id for e in entries}
            )
        return [
            {
                "name": names.get(e.institution_id, ""),
                "round": e.round,
                "status": e.status,
                "bucket": e.bucket,
                "notes": e.notes,
            }
            for e in entries
        ]

    async def deadlines(self, student_id: UUID) -> list[dict[str, Any]]:
        """Milestones of the list, soonest first."""
        async with self._uow() as uow:
            entries = await uow.shortlist.entries(student_id)
            by_entry = {e.id: e.institution_id for e in entries}
            milestones = await uow.deadlines.milestones_of_entries(list(by_entry))
            names = await uow.deadlines.institution_names(set(by_entry.values()))
        rows = [
            {
                "institution": names.get(by_entry[m.list_entry_id], ""),
                "kind": m.kind,
                "due_utc": m.due_utc.isoformat() if m.due_utc else None,
                "predicted": m.predicted,
            }
            for m in milestones
        ]
        return sorted(rows, key=lambda r: (r["due_utc"] is None, r["due_utc"] or ""))

    async def courses(self, student_id: UUID) -> list[dict[str, Any]]:
        """Stored courses with grades."""
        async with self._uow() as uow:
            rows = await uow.courses.list_for(student_id)
        return [_row(c) for c in rows if c.included]
