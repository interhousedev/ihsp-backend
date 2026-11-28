"""The stats day follows Tashkent time, not UTC."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from app.modules.library.infrastructure.redis_stats import RedisStatsRecorder


def test_day_key_is_the_tashkent_date_after_utc_evening() -> None:
    clock = SimpleNamespace(now=lambda: datetime(2026, 11, 27, 20, 0, tzinfo=UTC))
    recorder = RedisStatsRecorder(cast(Any, None), cast(Any, clock))

    assert recorder._day() == "2026-11-28"
