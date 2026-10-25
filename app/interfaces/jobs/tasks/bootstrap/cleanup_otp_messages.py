"""Task bootstrap.cleanup_otp_messages (every minute): delete stale OTP messages."""

from app.bootstrap.otp_cleanup import delete_due_otp_messages
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="bootstrap.cleanup_otp_messages")
async def cleanup_otp_messages() -> int:
    """Remove Telegram messages with one-time codes five minutes after sending."""
    container = get_container()
    return await delete_due_otp_messages(
        container.redis, container.telegram, container.clock.now()
    )
