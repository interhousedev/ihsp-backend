"""Waiting server-side for a lesson's EMIS fetch (A3).

Most AI clients have no sleep tool, so "wait and retry" would burn calls at once. Each
call waits here instead, holding no database session; three calls cover the ceiling.
"""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from app.shared.clock import Clock
from app.shared.contracts.mcp_academic import MaterialFetch, McpAcademicTools

POLL_SECONDS: float = 1
LONG_POLL_STEPS = 20
CEILING_SECONDS = 60
MAX_WAITERS = 20  # per process; above it a call answers pending at once
_gate = asyncio.Semaphore(MAX_WAITERS)


def deadline_of(fetch: MaterialFetch) -> datetime:
    """When the client stops waiting for this fetch."""
    return fetch.started_at + timedelta(seconds=CEILING_SECONDS)


def is_past_ceiling(fetch: MaterialFetch, clock: Clock) -> bool:
    """True from 60 seconds after the fetch began."""
    return clock.now() >= deadline_of(fetch)


async def wait_for_fetch(
    tools: McpAcademicTools, clock: Clock, lesson_id: UUID, fetch: MaterialFetch
) -> MaterialFetch:
    """Poll until the fetch ends, this call's wait is over or the ceiling comes."""
    if _gate.locked():
        return fetch
    left = int((deadline_of(fetch) - clock.now()).total_seconds())
    async with _gate:
        for _ in range(min(LONG_POLL_STEPS, left)):
            await asyncio.sleep(POLL_SECONDS)
            current = await tools.material_fetch(lesson_id)
            if current is None:  # expired while waiting: the worker is gone
                return MaterialFetch(
                    job_id=fetch.job_id,
                    status="failed",
                    started_at=fetch.started_at,
                    reason="emis_busy",
                )
            fetch = current
            if fetch.status != "running":
                break
    return fetch
