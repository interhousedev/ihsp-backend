"""Voice notes and audio files: transcribed, shown briefly, then answered as text."""

from typing import Any

from app.interfaces.bot.assistant.service import bot_assistant, has_assistant_role
from app.interfaces.bot.assistant.voice import (
    clip_of,
    shorten_transcript,
    transcribe_clip,
    video_clip_of,
)
from app.interfaces.bot.routers.common.assistant.handlers.ask import (
    answer_turn,
    new_stream,
)
from app.interfaces.bot.utilities.html import escape
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.types import Message


async def ask_voice(
    message: Message, bot: Bot, actor: Actor, container: Any, i18n: I18nContext
) -> None:
    """Transcribe the recording, show the transcript, answer it like typed text.

    Caps, rate limit and AI access are checked before and inside the transcription;
    a refusal reaches the user as for text (the error middleware speaks the error).
    """
    assistant = bot_assistant(container)
    if assistant is None:  # the router's filter keeps this from happening
        return
    if not has_assistant_role(actor):
        await message.answer(i18n("bot-ai-no-assistant"))
        return
    clip = clip_of(message) or video_clip_of(message)
    if clip is None:
        return
    stream = new_stream(bot, message)
    await stream.typing()
    transcript = (await transcribe_clip(bot, assistant, actor, clip)).strip()
    if not transcript:
        await message.answer(i18n("bot-ai-voice-empty"))
        return
    shown = escape(shorten_transcript(transcript))
    await message.answer(i18n("bot-ai-voice-heard", text=shown))
    await answer_turn(bot, stream, assistant, actor, i18n, transcript, [])
