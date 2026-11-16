"""Voice answers: request shape, caps, consent, no persistence, fake mode."""

import base64
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.voice import VoiceService
from app.modules.admission.domain.career import CareerQuestion
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    ConsentRequiredError,
    VoiceFormatError,
    VoiceTooLargeError,
    VoiceTooLongError,
)
from app.modules.admission.domain.voice import PCM_RATE, sniff, wav
from app.modules.admission.infrastructure.voice_openrouter import (
    FAKE_TRANSCRIPT,
    FakeVoice,
    OpenRouterVoice,
)
from app.modules.admission.ports.consent import AI
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiAccessRevokedError, AiProviderError
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeConsents

import httpx
import pytest

USER = new_id()
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 60
CAPS = SimpleNamespace(
    admit_voice_max_bytes=1024, admit_voice_max_seconds=120, admit_speech_max_chars=10
)


class Access:
    def __init__(self, blocked: bool = False) -> None:
        self.blocked = blocked

    def blocks(self, scope: str) -> bool:
        return self.blocked


class Limits:
    def __init__(self, blocked: bool = False) -> None:
        self.access = Access(blocked)

    async def for_user(self, user_id: UUID) -> Any:
        return CAPS

    async def ai_access(self, user_id: UUID) -> Access:
        return self.access


class Pending:
    def __init__(self, log: list[Any]) -> None:
        self.log = log

    async def finish(self, usage: Any = None, *, error: str | None = None) -> None:
        self.log.append(("finish", usage, error))


class Ledger:
    def __init__(self) -> None:
        self.log: list[Any] = []

    def begin(self, *, model: str, task: str | None) -> Pending:
        self.log.append(("begin", model, task))
        return Pending(self.log)


class Limiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.keys.append(key)


class Questions:
    def __init__(self, q: CareerQuestion) -> None:
        self.q = q
        self.writes = 0

    async def get_question(self, question_id: UUID) -> CareerQuestion | None:
        return self.q if question_id == self.q.id else None


class Uow:
    """Read-only UoW; any write attribute is absent, so a write would fail."""

    def __init__(self, career: Questions) -> None:
        self.career = career
        self.committed = False

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class Recording:
    """VoiceAi that records what it got."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def transcribe(self, user_id: UUID, data: bytes, fmt: str, lang: str) -> str:
        self.calls.append(("stt", data, fmt, lang))
        return "hello"

    async def speak(self, user_id: UUID, text: str, locale: str) -> bytes:
        self.calls.append(("tts", text, locale))
        return wav(b"")


QUESTION = CareerQuestion(
    new_id(), "interests", {"uz": "Savol", "ru": "Вопрос", "en": "What do you enjoy?"}
)


def _service(consent: bool = True) -> tuple[Any, ...]:
    voice, limiter = Recording(), Limiter()
    uows: list[Uow] = []

    def factory() -> Uow:
        uows.append(Uow(Questions(QUESTION)))
        return uows[-1]

    async def daily(user_id: UUID) -> int | None:
        return 40

    svc = VoiceService(
        factory,  # type: ignore[arg-type]
        voice,
        limiter,  # type: ignore[arg-type]
        daily,
        Limits(),  # type: ignore[arg-type]
        FakeConsents({USER: frozenset({AI})} if consent else {}),
    )
    return svc, voice, limiter, uows


CTX: Any = SimpleNamespace(user_id=USER)


async def test_transcribe_requires_ai_consent() -> None:
    svc, voice, limiter, _ = _service(consent=False)
    with pytest.raises(ConsentRequiredError):
        await svc.transcribe(CTX, WEBM, 5, "ru")
    assert voice.calls == [] and limiter.keys == []


async def test_transcribe_passes_bytes_once_and_stores_nothing() -> None:
    svc, voice, limiter, uows = _service()
    assert await svc.transcribe(CTX, WEBM, 5, "ru") == "hello"
    assert voice.calls == [("stt", WEBM, "webm", "ru")]
    assert uows == []  # no unit of work opened: nothing persisted
    assert limiter.keys == [
        f"admission:voice:minute:{USER}",
        f"admission:voice:{USER}",
    ]


async def test_transcribe_caps_and_format() -> None:
    svc, voice, _, _ = _service()
    with pytest.raises(VoiceTooLargeError):
        await svc.transcribe(CTX, WEBM + b"\x00" * 2000, 5, "en")
    with pytest.raises(VoiceTooLongError):
        await svc.transcribe(CTX, WEBM, 121, "en")
    with pytest.raises(VoiceFormatError):
        await svc.transcribe(CTX, b"<html>" * 4, 5, "en")
    assert voice.calls == []
    assert await svc.max_bytes(USER) == 1024


async def test_unknown_locale_falls_back_to_english() -> None:
    svc, voice, _, _ = _service()
    await svc.transcribe(CTX, WEBM, 5, "de")
    assert voice.calls[0][3] == "en"


async def test_speak_reads_only_stored_question_truncated() -> None:
    svc, voice, _, uows = _service()
    audio = await svc.speak(CTX, QUESTION.id, "en")
    assert audio.startswith(b"RIFF")
    assert voice.calls == [("tts", "What do yo", "en")]
    assert not uows[0].committed
    with pytest.raises(AdmissionNotFoundError):
        await svc.speak(CTX, new_id(), "en")


def test_sniff_and_wav_header() -> None:
    assert sniff(WEBM[:16]) == "webm"
    assert sniff(b"OggS" + b"\x00" * 12) == "ogg"
    assert sniff(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4) == "m4a"
    assert sniff(b"plain text here!") is None
    out = wav(b"\x01\x00" * 10)
    assert out[:4] == b"RIFF" and out[8:12] == b"WAVE"
    assert int.from_bytes(out[24:28], "little") == PCM_RATE
    assert int.from_bytes(out[40:44], "little") == 20


def _router(handler: Any, ledger: Ledger, blocked: bool = False) -> OpenRouterVoice:
    return OpenRouterVoice(
        api_key="k",
        base_url="https://openrouter.test/api/v1/",
        app_url="https://app.test",
        app_title="T",
        timeout_seconds=5,
        models={
            AiTask.ADMIT_VOICE_TRANSCRIBE: "stt/model",
            AiTask.ADMIT_QUESTION_SPEECH: "tts/model",
        },
        limits=Limits(blocked),  # type: ignore[arg-type]
        ledger=ledger,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_openrouter_transcription_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": " hi ", "usage": {"seconds": 2}})

    ledger = Ledger()
    text = await _router(handler, ledger).transcribe(USER, WEBM, "webm", "uz")
    assert text == "hi"
    req = seen[0]
    assert str(req.url) == "https://openrouter.test/api/v1/audio/transcriptions"
    assert req.headers["authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["model"] == "stt/model"
    assert body["input_audio"] == {
        "data": base64.b64encode(WEBM).decode(),
        "format": "webm",
    }
    assert body["language"] == "uz"
    assert body["provider"] == {"data_collection": "deny"}
    assert ledger.log == [
        ("begin", "stt/model", AiTask.ADMIT_VOICE_TRANSCRIBE),
        ("finish", {"seconds": 2}, None),
    ]


async def test_openrouter_speech_wraps_pcm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/audio/speech")
        assert body["response_format"] == "pcm" and body["input"] == "Q?"
        assert body["provider"] == {"data_collection": "deny"}
        return httpx.Response(200, content=b"\x00\x00" * 4)

    out = await _router(handler, Ledger()).speak(USER, "Q?", "en")
    assert out[:4] == b"RIFF" and out.endswith(b"\x00" * 8)


async def test_openrouter_failure_and_revoked_access() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    ledger = Ledger()
    with pytest.raises(AiProviderError):
        await _router(fail, ledger).transcribe(USER, WEBM, "webm", "en")
    assert ledger.log[-1] == ("finish", None, "HTTPStatusError")

    calls: list[Any] = []
    with pytest.raises(AiAccessRevokedError):
        await _router(calls.append, Ledger(), blocked=True).transcribe(
            USER, WEBM, "webm", "en"
        )
    assert calls == []


async def test_fake_voice() -> None:
    fake = FakeVoice()
    assert await fake.transcribe(USER, WEBM, "webm", "en") == FAKE_TRANSCRIPT
    assert (await fake.speak(USER, "x", "en"))[:4] == b"RIFF"
