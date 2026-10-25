"""bootstrap.cleanup_otp_messages deletes the Telegram messages that carried codes."""

from app.bootstrap.otp_cleanup import delete_due_otp_messages
from app.modules.identity.infrastructure.otp_sender import CLEANUP_KEY
from tests.fakes.clock import FixedClock

from fakeredis.aioredis import FakeRedis


class RecordingTelegram:
    """TelegramSender that records deletions."""

    def __init__(self) -> None:
        """Start empty."""
        self.deleted: list[tuple[int, int]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Record the deletion."""
        self.deleted.append((chat_id, message_id))


async def test_only_due_messages_are_deleted(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """Messages whose time has come go; later ones stay in the set."""
    now = clock.now().timestamp()
    await redis.zadd(CLEANUP_KEY, {"10:1": now - 5, "10:2": now - 1, "11:3": now + 300})
    telegram = RecordingTelegram()

    handled = await delete_due_otp_messages(
        redis, telegram, clock.now()  # type: ignore[arg-type]
    )

    assert handled == 2
    assert telegram.deleted == [(10, 1), (10, 2)]
    assert await redis.zrange(CLEANUP_KEY, 0, -1) == ["11:3"]
