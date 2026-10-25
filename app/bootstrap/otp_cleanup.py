"""Deletes the Telegram messages that carried one-time codes once they are stale."""

from datetime import datetime

from app.modules.identity.infrastructure.otp_sender import CLEANUP_KEY
from app.shared.contracts.notify import TelegramSender

from redis.asyncio import Redis

BATCH = 200


async def delete_due_otp_messages(
    redis: Redis, telegram: TelegramSender, now: datetime
) -> int:
    """Delete messages whose time (score) has come; return how many were handled.

    Members of the zset `tg:otp-msgs` look like `<chat_id>:<message_id>`. A message
    Telegram refuses to delete is dropped from the set too (the sender only logs).
    """
    due: list[str] = await redis.zrangebyscore(
        CLEANUP_KEY, "-inf", now.timestamp(), start=0, num=BATCH
    )
    for member in due:
        chat_id, _, message_id = member.partition(":")
        await telegram.delete_message(int(chat_id), int(message_id))
        await redis.zrem(CLEANUP_KEY, member)
    return len(due)
