"""AI chat voice input: which media are speech, and the caps checked before download.

Telegram voice notes, audio files and (round) videos. Video cannot be turned into
audio here (no extractor in the image), so it is recognised and refused.
"""

import datetime as dt
from typing import Any

from app.interfaces.bot.assistant.voice import (
    Clip,
    check_clip,
    clip_of,
    is_video,
    shorten_transcript,
)
from app.modules.ai.domain.errors import (
    VoiceFormatError,
    VoiceTooLargeError,
    VoiceTooLongError,
)
from app.modules.ai.domain.voice import MAX_BYTES, MAX_SECONDS

import pytest
from aiogram.types import Audio, Message, Video, VideoNote, Voice

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def _message(**content: Any) -> Message:
    base = {"message_id": 1, "date": NOW, "chat": {"id": 1, "type": "private"}}
    return Message.model_validate({**base, **content})


def _voice(**overrides: Any) -> Voice:
    data = {
        "file_id": "voice-file",
        "file_unique_id": "vu",
        "duration": 4,
        "file_size": 2000,
        **overrides,
    }
    return Voice.model_validate(data)


def test_a_voice_message_is_speech_with_its_size_and_length() -> None:
    clip = clip_of(_message(voice=_voice(mime_type="audio/ogg")))
    assert clip == Clip(
        file_id="voice-file", size=2000, duration=4, content_type="audio/ogg"
    )


def test_a_voice_message_without_mime_type_is_ogg() -> None:
    clip = clip_of(_message(voice=_voice()))
    assert clip is not None
    assert clip.content_type == "audio/ogg"


def test_an_audio_file_keeps_its_mime_type() -> None:
    audio = Audio.model_validate(
        {
            "file_id": "a",
            "file_unique_id": "au",
            "duration": 30,
            "mime_type": "audio/mpeg",
            "file_size": 900,
        }
    )
    clip = clip_of(_message(audio=audio))
    assert clip is not None
    assert (clip.duration, clip.content_type) == (30, "audio/mpeg")


def test_video_notes_and_videos_are_not_speech_here() -> None:
    note = VideoNote.model_validate(
        {"file_id": "n", "file_unique_id": "nu", "length": 240, "duration": 5}
    )
    video = Video.model_validate(
        {"file_id": "v", "file_unique_id": "vu", "width": 1, "height": 1, "duration": 5}
    )
    for message in (_message(video_note=note), _message(video=video)):
        assert clip_of(message) is None
        assert is_video(message)


def test_a_text_message_is_neither_speech_nor_video() -> None:
    message = _message(text="hello")
    assert clip_of(message) is None
    assert not is_video(message)


def test_a_clip_of_exactly_the_longest_allowed_length_passes() -> None:
    check_clip(Clip("f", 1000, MAX_SECONDS, "audio/ogg"))


def test_a_clip_longer_than_the_limit_is_refused_before_download() -> None:
    with pytest.raises(VoiceTooLongError) as error:
        check_clip(Clip("f", 1000, MAX_SECONDS + 1, "audio/ogg"))
    assert error.value.params == {"max_seconds": MAX_SECONDS}


def test_a_file_at_the_byte_cap_passes_and_one_byte_more_is_refused() -> None:
    check_clip(Clip("f", MAX_BYTES, 10, "audio/ogg"))
    with pytest.raises(VoiceTooLargeError):
        check_clip(Clip("f", MAX_BYTES + 1, 10, "audio/ogg"))


def test_an_unreported_size_is_checked_after_the_download_instead() -> None:
    check_clip(Clip("f", None, 10, "audio/ogg"))


def test_a_format_the_model_cannot_read_is_refused_before_download() -> None:
    with pytest.raises(VoiceFormatError):
        check_clip(Clip("f", 1000, 10, "application/pdf"))


def test_a_short_transcript_is_shown_whole() -> None:
    assert shorten_transcript("What is 2 + 2?") == "What is 2 + 2?"


def test_a_long_transcript_is_shortened_with_an_ellipsis() -> None:
    shown = shorten_transcript("word " * 200)
    assert shown.endswith("…")
    assert len(shown) <= 300
