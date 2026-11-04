"""Voice, audio and video messages in the AI chat: transcribed, then answered as typed.

The bot checks the caps before it downloads anything from Telegram; the transcription
use case (fake here) does the rate limit, the AI access check and the usage ledger.
"""

from typing import Any

from app.interfaces.bot.assistant import voice as voice_module
from app.interfaces.bot.assistant.video import MAX_VIDEO_BYTES, ExtractError
from app.modules.ai.domain.errors import AiLimitReachedError
from app.modules.ai.domain.voice import MAX_BYTES
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import AiAccessRevokedError
from tests.bot.support.fake_ai import FakeAi, delta, done
from tests.bot.support.fakes import TEACHER_TG
from tests.bot.support.harness import Harness

import pytest
from aiogram.methods import GetFile, SendMessage

GUEST = 8888
VOICE = {
    "file_id": "voice-file",
    "file_unique_id": "vu",
    "duration": 4,
    "mime_type": "audio/ogg",
    "file_size": 2000,
}


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant with a scripted transcription."""
    fake = FakeAi()
    harness.world.container.ai = fake
    harness.session.download_data = b"OggS-recording"
    return fake


def _texts(harness: Harness) -> list[str]:
    return [m.text or "" for m in harness.session.calls(SendMessage)]


def _downloads(harness: Harness) -> int:
    return len(harness.session.calls(GetFile))


async def test_a_voice_message_is_transcribed_shown_and_answered(
    harness: Harness, ai: FakeAi
) -> None:
    ai.transcripts.append("What is two plus two?")
    ai.play([delta("Four."), done("Four.")])

    await harness.send_media("voice", VOICE)

    assert ai.transcribed == [
        {
            "data": b"OggS-recording",
            "duration_ms": 4000,
        }
    ]
    assert ai.sent[0]["text"] == "What is two plus two?"
    texts = _texts(harness)
    assert "bot-ai-voice-heard[text=What is two plus two?]" in texts[0]
    assert "Four." in texts[-1]


async def test_the_recording_is_not_stored_as_a_file(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send_media("voice", VOICE)

    assert harness.world.files.stored == []


async def test_access_and_rate_are_checked_before_the_download(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send_media("voice", VOICE)

    assert len(ai.prechecks) == 1
    assert ai.transcribed  # the recording went on to the transcription


async def test_a_revoked_student_costs_no_download_and_no_ffmpeg(
    harness: Harness, ai: FakeAi, extracted: list[dict[str, Any]]
) -> None:
    ai.precheck_refusal = AiAccessRevokedError(params={"scope": "chat"})

    await harness.send_media("video_note", VIDEO_NOTE)

    assert _downloads(harness) == 0
    assert extracted == []
    assert ai.transcribed == []
    assert AiAccessRevokedError.message_key in harness.last_text()


async def test_a_rate_limited_student_costs_no_download(
    harness: Harness, ai: FakeAi
) -> None:
    ai.precheck_refusal = RateLimitedError(params={"retry_after": 30})

    await harness.send_media("voice", VOICE)

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert RateLimitedError.message_key in harness.last_text()


async def test_a_long_recording_is_refused_before_any_download(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send_media("voice", {**VOICE, "duration": 121})

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert "ai-voice-too-long" in harness.last_text()


async def test_a_recording_over_the_size_cap_is_refused_before_download(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send_media("voice", {**VOICE, "file_size": MAX_BYTES + 1})

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert "ai-voice-too-large" in harness.last_text()


async def test_an_unreported_size_is_capped_while_downloading(
    harness: Harness, ai: FakeAi
) -> None:
    harness.session.download_data = b"x" * (MAX_BYTES + 1)

    await harness.send_media("voice", {**VOICE, "file_size": None})

    assert ai.transcribed == []
    assert "ai-voice-too-large" in harness.last_text()


async def test_an_audio_file_is_transcribed_with_its_own_format(
    harness: Harness, ai: FakeAi
) -> None:
    ai.transcripts.append("hello")
    audio = {
        "file_id": "a",
        "file_unique_id": "au",
        "duration": 30,
        "mime_type": "audio/mpeg",
        "file_size": 900,
    }

    await harness.send_media("audio", audio)

    assert ai.transcribed[0]["data"] == b"OggS-recording"
    assert ai.sent[0]["text"] == "hello"


async def test_an_audio_format_the_model_cannot_read_is_refused(
    harness: Harness, ai: FakeAi
) -> None:
    audio = {
        "file_id": "a",
        "file_unique_id": "au",
        "duration": 30,
        "mime_type": "application/pdf",
        "file_size": 900,
    }

    await harness.send_media("audio", audio)

    assert _downloads(harness) == 0
    assert "ai-voice-format" in harness.last_text()


VIDEO_NOTE = {"file_id": "n", "file_unique_id": "nu", "length": 240, "duration": 5}
VIDEO = {
    "file_id": "v",
    "file_unique_id": "vu",
    "width": 1,
    "height": 1,
    "duration": 5,
    "file_size": 3_000_000,
}


@pytest.fixture
def extracted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ffmpeg: the extractor returns the audio and records its input."""
    calls: list[dict[str, Any]] = []

    async def fake_extract(data: bytes, **kwargs: Any) -> bytes:
        calls.append({"data": data})
        return b"OggS-extracted"

    monkeypatch.setattr(voice_module, "extract_audio", fake_extract)
    return calls


async def test_a_video_note_is_transcribed_from_its_extracted_audio(
    harness: Harness, ai: FakeAi, extracted: list[dict[str, Any]]
) -> None:
    ai.transcripts.append("Explain photosynthesis")
    ai.play([delta("Plants..."), done("Plants...")])

    await harness.send_media("video_note", VIDEO_NOTE)

    assert extracted == [{"data": b"OggS-recording"}]
    assert ai.transcribed == [
        {
            "data": b"OggS-extracted",
            "duration_ms": 5000,
        }
    ]
    assert ai.sent[0]["text"] == "Explain photosynthesis"


async def test_a_video_is_transcribed_the_same_way(
    harness: Harness, ai: FakeAi, extracted: list[dict[str, Any]]
) -> None:
    await harness.send_media("video", VIDEO)

    assert len(ai.transcribed) == 1
    assert ai.transcribed[0]["data"] == b"OggS-extracted"


async def test_a_video_over_the_video_cap_is_refused_before_download(
    harness: Harness, ai: FakeAi, extracted: list[dict[str, Any]]
) -> None:
    await harness.send_media("video", {**VIDEO, "file_size": MAX_VIDEO_BYTES + 1})

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert "ai-voice-too-large" in harness.last_text()


async def test_a_long_video_is_refused_before_download(
    harness: Harness, ai: FakeAi, extracted: list[dict[str, Any]]
) -> None:
    await harness.send_media("video", {**VIDEO, "duration": 121})

    assert _downloads(harness) == 0
    assert "ai-voice-too-long" in harness.last_text()


async def test_a_video_whose_audio_cannot_be_extracted_is_unsupported(
    harness: Harness, ai: FakeAi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(data: bytes, **kwargs: Any) -> bytes:
        raise ExtractError("no ffmpeg")

    monkeypatch.setattr(voice_module, "extract_audio", broken)

    await harness.send_media("video_note", VIDEO_NOTE)

    assert ai.transcribed == []
    assert "bot-ai-video-unsupported" in harness.last_text()


async def test_an_empty_transcript_asks_for_another_try(
    harness: Harness, ai: FakeAi
) -> None:
    ai.transcripts.append("")

    await harness.send_media("voice", VOICE)

    assert ai.sent == []
    assert "bot-ai-voice-empty" in harness.last_text()


async def test_revoked_ai_access_is_refused_as_for_text(
    harness: Harness, ai: FakeAi
) -> None:
    ai.transcripts.append(AiAccessRevokedError(params={"scope": "chat"}))

    await harness.send_media("voice", VOICE)

    assert ai.sent == []
    assert AiAccessRevokedError.message_key in harness.last_text()


async def test_a_limited_student_is_told_as_for_text(
    harness: Harness, ai: FakeAi
) -> None:
    ai.transcripts.append(AiLimitReachedError(params={"limit": 5}))

    await harness.send_media("voice", VOICE)

    assert AiLimitReachedError.message_key in harness.last_text()


async def test_a_teacher_without_the_assistant_gets_the_same_notice(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send_media("voice", VOICE, user_id=TEACHER_TG)

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert "bot-ai-no-assistant" in harness.last_text()


async def test_a_guest_voice_message_gets_a_text_notice_and_no_model_call(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send("/start", user_id=GUEST)
    await harness.press("sm:guest", user_id=GUEST)

    await harness.send_media("voice", VOICE, user_id=GUEST)

    assert _downloads(harness) == 0
    assert ai.transcribed == []
    assert harness.last_text() == "bot-guest-voice-unsupported"
