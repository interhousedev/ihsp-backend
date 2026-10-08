"""Task ``identity.apply_otp_resets``: unlink Telegram accounts of due OTP resets."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="identity.apply_otp_resets")
async def apply_otp_resets() -> int:
    """Run every 10 minutes; returns how many users were reset (ID-24)."""
    container = get_container()
    count: int = await container.identity.auth.apply_otp_resets.execute()
    return count
