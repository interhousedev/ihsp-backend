"""The engine has a bounded pool, a wait limit and a statement timeout."""

from typing import Any

from app.shared.db.engine import make_engine

import pytest
from sqlalchemy import event
from sqlalchemy.pool import QueuePool


class StopConnect(Exception):  # noqa: N818
    """Raised by the connect hook so no real connection is attempted."""


def test_the_pool_policy_and_statement_timeout_are_applied() -> None:
    """PERF: overflow and wait are bounded; every connection has a statement timeout."""
    engine = make_engine(
        "postgresql+asyncpg://u:p@localhost:1/db",
        3,
        max_overflow=2,
        pool_timeout=4.0,
        statement_timeout_ms=1234,
    )
    pool = engine.pool
    assert isinstance(pool, QueuePool)

    assert pool.size() == 3
    assert pool._max_overflow == 2  # noqa: SLF001
    assert pool._timeout == 4.0  # noqa: SLF001
    seen: list[dict[str, Any]] = []

    @event.listens_for(engine.sync_engine, "do_connect")
    def capture(dialect: Any, record: Any, cargs: Any, cparams: Any) -> None:
        seen.append(dict(cparams))
        raise StopConnect

    with pytest.raises(StopConnect):
        engine.sync_engine.raw_connection()
    assert seen[0]["server_settings"] == {"statement_timeout": "1234"}
