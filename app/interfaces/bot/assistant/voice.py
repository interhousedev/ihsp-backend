"""Speech in the AI chat: a voice note or an audio file is transcribed, then answered.

The caps (length, size, format) are checked before Telegram is asked for the file.
The recording is held in memory only and never stored; the transcription use case
(`container.ai.transcribe_audio`) applies the rate limit, the AI access check and
the usage ledger, like for any other model call.

Video (video messages and round video notes) is cut down to its audio by ffmpeg
(`video.py`), within its own size cap; the audio then goes through the same path.
"""

from dataclasses import dataclass
from typing import Final

from app.interfaces.bot.assistant.media import download_capped
from app.interfaces.bot.assistant.service import BotAssistant
from app.interfaces.bot.assistant.video import (
    MAX_VIDEO_BYTES,
    ExtractError,
    extract_audio,
)
from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    FileTooLargeError,
)
from app.modules.ai.domain.errors import (
    VoiceFormatError,
    VoiceTooLargeError,
    VoiceTooLongError,
)
from app.modules.ai.domain.voice import (
    AUDIO_FORMATS,
    MAX_BYTES,
    MAX_SECONDS,
    audio_format,
)
from app.shared.actor import Actor
from app.shared.base_error import BaseError

from aiogram import Bot
from aiogram.types import Message

DEFAULT_VOICE_TYPE: Final = "audio/ogg"  # Telegram voice notes are Ogg Opus
VIDEO_TYPE: Final = "video/mp4"
SHOWN_CHARS: Final = 300  # the transcript shown back to the user
MEGABYTE: Final = 1024 * 1024


class VideoUnsupportedError(BaseError):
    """The audio of a video could not be read (no ffmpeg, a broken or silent file)."""

    code = "bot/ai-video-unsupported"
    status = 422
    message_key = "bot-ai-video-unsupported"


@dataclass(frozen=True, slots=True)
class Clip:
    """A recording as Telegram describes it, before anything is downloaded."""

    file_id: str
    size: int | None
    duration: int
    content_type: str | None
    video: bool = False


def clip_of(message: Message) -> Clip | None:
    """The speech of a voice note or an audio file; None for any other message."""
    if message.voice is not None:
        voice = message.voice
        return Clip(
            voice.file_id,
            voice.file_size,
            voice.duration,
            voice.mime_type or DEFAULT_VOICE_TYPE,
        )
    if message.audio is not None:
        audio = message.audio
        return Clip(audio.file_id, audio.file_size, audio.duration, audio.mime_type)
    return None


def video_clip_of(message: Message) -> Clip | None:
    """A video message or a round video note; its audio is extracted before use."""
    video = message.video or message.video_note
    if video is None:
        return None
    return Clip(video.file_id, video.file_size, video.duration, VIDEO_TYPE, video=True)


def is_video(message: Message) -> bool:
    """True for a video message or a round video note."""
    return message.video is not None or message.video_note is not None


def check_clip(clip: Clip) -> None:
    """Refuse a recording over the length, size or format limits (no download yet)."""
    if clip.duration > MAX_SECONDS:
        raise VoiceTooLongError(params={"max_seconds": MAX_SECONDS})
    limit = MAX_VIDEO_BYTES if clip.video else MAX_BYTES
    if clip.size is not None and clip.size > limit:
        raise VoiceTooLargeError(params={"max_mb": limit // MEGABYTE})
    if not clip.video and audio_format(clip.content_type) is None:
        formats = ", ".join(sorted(set(AUDIO_FORMATS.values())))
        raise VoiceFormatError(params={"formats": formats})


async def transcribe_clip(
    bot: Bot, assistant: BotAssistant, actor: Actor, clip: Clip
) -> str:
    """Download the checked recording in memory and return its transcript.

    A video is cut to its audio first; the audio is capped like a voice note.
    """
    check_clip(clip)
    await assistant.check_transcribe(actor)
    limit = MAX_VIDEO_BYTES if clip.video else MAX_BYTES
    try:
        data = await download_capped(bot, clip.file_id, size=clip.size, limit=limit)
    except FileTooLargeError as error:
        raise VoiceTooLargeError(params={"max_mb": limit // MEGABYTE}) from error
    if clip.video:
        try:
            data = await extract_audio(data)
        except ExtractError as error:
            raise VideoUnsupportedError() from error
    return await assistant.transcribe(
        actor,
        data=data,
        duration_ms=clip.duration * 1000,
    )


def shorten_transcript(text: str) -> str:
    """The transcript on one line, cut to what fits in a short notice."""
    flat = " ".join(text.split())
    if len(flat) <= SHOWN_CHARS:
        return flat
    return flat[: SHOWN_CHARS - 1].rstrip() + "…"
