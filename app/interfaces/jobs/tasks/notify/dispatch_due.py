"""Task notify.dispatch_due: send due notifications to Telegram."""

from dataclasses import asdict
from typing import Any

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notify.dispatch_due")
async def dispatch_due() -> dict[str, Any]:
    """Kicked after every commit that wrote notifications, and every minute."""
    report = await get_container().notify.dispatch_due.execute()
    return asdict(report)
