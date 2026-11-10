"""The share link of an answer's OpenUI blocks, made on the first request."""

from typing import Any

from app.interfaces.bot.assistant.service import BotAssistant
from app.shared.actor import Actor
from app.shared.base_error import BaseError

import structlog

log = structlog.get_logger(__name__)


class VisualStaleError(Exception):
    """The token is unknown, expired or belongs to another user."""


class VisualFailedError(Exception):
    """The share could not be created."""


async def visual_url(
    assistant: BotAssistant, container: Any, actor: Actor, token: str
) -> str:
    """The 7-day share URL of the token's answer; only the owner's token works.

    The share is created on the first request and reused afterwards.
    """
    found = await assistant.store.visual_of(token, actor.user_id)
    if found is None:
        raise VisualStaleError
    url = await assistant.store.visual_url(token)
    if url is not None:
        return str(url)
    chat_id, seq = found
    try:
        view = await container.links.share_message.execute(
            actor, chat_id=chat_id, seq=seq
        )
    except BaseError as error:
        log.info("bot.ai.visualization_failed", error=type(error).__name__)
        raise VisualFailedError from error
    expires = view.link.expires_at
    ttl = int((expires - view.link.created_at).total_seconds()) if expires else 1
    await assistant.store.set_visual_url(token, view.url, ttl)
    return str(view.url)
