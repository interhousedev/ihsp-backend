"""TranscribeAudio: the bytes decide the format, and access and rate come first.

The use case takes the recording's real type from libmagic (the sniffer), never from
the type the client declared. `precheck` refuses before any download, so a refused
student costs no download and no ffmpeg run.
"""

from types import SimpleNamespace
from typing import Any

from app.modules.ai.application.transcribe_audio import TranscribeAudio
from app.modules.ai.domain.errors import VoiceFormatError
from app.modules.ai.domain.voice import sniffed_format
from app.shared.actor import Actor, Role
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import AiAccessRevokedError
from app.shared.ids import new_id

import pytest

PDF = b"%PDF-1.7 not audio at all"
MP3 = b"ID3\x04\x00" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64


class SniffingFake:
    """Looks at the first bytes, like libmagic does."""

    async def sniff(self, head: bytes) -> str:
        if head.startswith(b"%PDF"):
            return "application/pdf"
        if head.startswith(b"ID3"):
            return "audio/mpeg"
        if head.startswith(b"OggS"):
            return "audio/ogg"
        return "application/octet-stream"


class FakeBudget:
    def __init__(self, revoked: bool = False) -> None:
        self.revoked = revoked

    async def require_access(self, user_id: Any, scope: str) -> None:
        if self.revoked:
            raise AiAccessRevokedError(params={"scope": scope})

    async def check(self, user_id: Any, assistant: Any, estimate: int) -> None:
        return None

    async def add(self, user_id: Any, tokens: int, assistant: Any) -> None:
        return None


class FakeRateLimiter:
    def __init__(self, spent: bool = False) -> None:
        self.spent = spent
        self.checked: list[str] = []
        self.hits: list[str] = []

    async def check(self, key: str, *, limit: int) -> None:
        self.checked.append(key)
        if self.spent:
            raise RateLimitedError(params={"retry_after": 20})

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.hits.append(key)
        return 1


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"text": "hello", "usage": {}}


class FakeLocale:
    async def locale_of(self, user_id: Any) -> str:
        return "en"


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        model="m",
        budget_weight=1,
        tuning=None,
        output_tokens=lambda n: n,
        provider=lambda: None,
    )


def _service(
    *,
    budget: FakeBudget | None = None,
    rate: FakeRateLimiter | None = None,
    llm: FakeLlm | None = None,
) -> tuple[TranscribeAudio, FakeLlm, FakeRateLimiter]:
    llm = llm or FakeLlm()
    rate = rate or FakeRateLimiter()
    settings = SimpleNamespace(ai_profile=lambda task: _profile())
    service = TranscribeAudio(
        llm=llm,  # type: ignore[arg-type]
        budget=budget or FakeBudget(),  # type: ignore[arg-type]
        rate_limiter=rate,  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        locale=FakeLocale(),  # type: ignore[arg-type]
        sniffer=SniffingFake(),
    )
    return service, llm, rate


def _actor() -> Actor:
    return Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))


async def test_a_pdf_declared_as_ogg_is_refused_before_the_model() -> None:
    service, llm, _ = _service()

    with pytest.raises(VoiceFormatError):
        await service.execute(_actor(), data=PDF, duration_ms=1000)

    assert llm.calls == []


async def test_the_format_sent_to_the_model_is_the_sniffed_one() -> None:
    service, llm, _ = _service()

    await service.execute(_actor(), data=MP3, duration_ms=1000)

    part = llm.calls[0]["messages"][0]["content"][1]
    assert part["input_audio"]["format"] == "mp3"


async def test_a_real_ogg_with_no_declared_type_is_accepted() -> None:
    service, llm, _ = _service()

    text = await service.execute(_actor(), data=OGG, duration_ms=500)

    assert text == "hello"
    assert llm.calls[0]["messages"][0]["content"][1]["input_audio"]["format"] == "ogg"


async def test_precheck_refuses_revoked_access_and_counts_nothing() -> None:
    service, _, rate = _service(budget=FakeBudget(revoked=True))

    with pytest.raises(AiAccessRevokedError):
        await service.precheck(_actor())

    assert rate.hits == []


async def test_precheck_refuses_a_spent_minute_and_counts_nothing() -> None:
    service, _, rate = _service(rate=FakeRateLimiter(spent=True))

    with pytest.raises(RateLimitedError):
        await service.precheck(_actor())

    assert rate.hits == []


async def test_precheck_passes_and_leaves_the_count_to_execute() -> None:
    service, _, rate = _service()

    await service.precheck(_actor())

    assert rate.checked and rate.hits == []


@pytest.mark.parametrize(
    ("mime", "fmt"),
    [
        ("audio/x-m4a", "m4a"),
        ("audio/mpeg", "mp3"),
        ("video/webm", "webm"),
        ("video/mp4", None),  # a video is not read as audio
        ("application/pdf", None),
    ],
)
def test_sniffed_types_map_to_the_formats_the_model_reads(
    mime: str, fmt: str | None
) -> None:
    assert sniffed_format(mime) == fmt
