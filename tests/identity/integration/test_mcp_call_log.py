"""B1: the call log table against PostgreSQL."""

from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.orm import McpCallLogRow
from app.modules.identity.infrastructure.orm import McpConnector as ConnectorRow
from app.modules.identity.infrastructure.repositories.mcp_call_log_repository import (
    SqlMcpCallLogRepository,
)
from app.modules.identity.infrastructure.repositories.user_repository import (
    SqlUserRepository,
)
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.ids import new_id
from tests.identity.integration.test_repositories import user_row

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SessionMaker = async_sessionmaker[AsyncSession]


def record(user_id: UUID, **changes: Any) -> McpCallRecord:
    """A successful call through a given user."""
    values: dict[str, Any] = {
        "user_id": user_id,
        "connector_id": None,
        "client_id": None,
        "server": "student",
        "tool": "get_marks",
        "scope": "marks:read",
        "read_only": True,
        "outcome": "ok",
        "error_code": None,
        "error_id": None,
        "duration_ms": 12,
        "arguments": {"subject_id": str(new_id())},
        "result_summary": {"count": 3},
        "ip": "203.0.113.9",
    }
    values.update(changes)
    return McpCallRecord(**values)


async def _user(sessions: SessionMaker) -> UUID:
    user = user_row()
    async with sessions() as session, session.begin():
        await SqlUserRepository(session).add(user)
    return user.id


async def test_a_row_round_trips(sessionmaker_in_tx: SessionMaker) -> None:
    """B1: every column is stored."""
    user_id = await _user(sessionmaker_in_tx)

    async with sessionmaker_in_tx() as session, session.begin():
        await SqlMcpCallLogRepository(session).add(record(user_id))

    async with sessionmaker_in_tx() as session:
        row = (
            await session.execute(
                select(McpCallLogRow).where(McpCallLogRow.user_id == user_id)
            )
        ).scalar_one()
    assert (row.server, row.tool, row.outcome) == ("student", "get_marks", "ok")
    assert row.ip == "203.0.113.9"
    assert row.result_summary == {"count": 3}
    assert row.connector_name is None


async def test_the_name_of_the_connector_is_copied_at_write_time(
    sessionmaker_in_tx: SessionMaker,
) -> None:
    """B1: the trace stays readable after the connector is deleted (no FK)."""
    user_id = await _user(sessionmaker_in_tx)
    connector_id = new_id()
    async with sessionmaker_in_tx() as session, session.begin():
        session.add(
            ConnectorRow(
                id=connector_id, user_id=user_id, name="My laptop", server="student"
            )
        )

    async with sessionmaker_in_tx() as session, session.begin():
        await SqlMcpCallLogRepository(session).add(
            record(user_id, connector_id=connector_id)
        )
        await session.execute(
            delete(ConnectorRow).where(ConnectorRow.id == connector_id)
        )

    async with sessionmaker_in_tx() as session:
        row = (
            await session.execute(
                select(McpCallLogRow).where(McpCallLogRow.connector_id == connector_id)
            )
        ).scalar_one()
    assert row.connector_name == "My laptop"
