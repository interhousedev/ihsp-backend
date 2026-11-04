"""HTTP: POST /v1/ai/transcriptions (speech to text; audio is never stored)."""

from datetime import UTC, datetime
from typing import Any, cast

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.ai import ROUTERS
from app.modules.ai.domain.usage import UsageEvent
from app.modules.ai.domain.voice import MAX_BYTES, MAX_SECONDS, RATE_PER_MINUTE
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingLlmGateway,
    UsageRecorder,
)
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.usage_context import bind_usage_actor, reset_usage_actor
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import ScriptedLlm, text_reply
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient

OGG = ("clip.ogg", b"OggS" + b"\x00" * 64, "audio/ogg")


class _Sink:
    """Keeps the usage events the recorder writes."""

    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def write(self, event: UsageEvent) -> None:
        self.events.append(event)


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor the next request runs as."""
    return {}


@pytest.fixture
async def api(
    make_harness: HarnessFactory, http_client: Any, current: dict[str, Actor]
) -> tuple[AiHarness, AsyncClient]:
    """The harness and a client whose requests run as `current["actor"]`."""
    h = make_harness()
    current["actor"] = h.student
    client = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, ai=h.services
    )
    return h, client


async def post(
    client: AsyncClient,
    clip: tuple[str, bytes, str],
    duration_ms: int = 4000,
) -> Any:
    """POST one recording as multipart form data."""
    name, data, content_type = clip
    return await client.post(
        "/v1/ai/transcriptions",
        files={"file": (name, data, content_type)},
        data={"duration_ms": str(duration_ms)},
    )


async def test_a_recording_becomes_text_and_is_counted_in_the_ledger_and_budget(
    make_harness: HarnessFactory, http_client: Any, current: dict[str, Actor]
) -> None:
    """AI voice: the transcript comes back; the call is in the ledger and the budget."""
    script = ScriptedLlm()
    script.push(text_reply("Salom, dars qachon?", tokens=40))
    sink = _Sink()
    recorder = UsageRecorder(sink, FixedClock(datetime(2026, 10, 6, 9, 0, tzinfo=UTC)))
    h = make_harness(llm=RecordingLlmGateway(cast(LlmGateway, script), recorder))
    current["actor"] = h.student
    client = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, ai=h.services
    )

    token = bind_usage_actor(h.student)
    try:
        response = await post(client, OGG)
    finally:
        reset_usage_actor(token)

    assert response.status_code == 200, response.text
    assert response.json() == {"text": "Salom, dars qachon?"}
    sent = script.requests[-1]
    assert sent["tuning"].task == "voice_transcribe"
    parts = sent["messages"][0]["content"]
    assert parts[1]["type"] == "input_audio"
    assert parts[1]["input_audio"]["format"] == "ogg"
    (event,) = sink.events
    assert event.task == "voice_transcribe"
    assert event.feature == "assistant"
    assert event.user_id == h.student.user_id
    assert event.role == "student"
    assert (event.input_tokens, event.output_tokens, event.success) == (40, 20, True)
    weight = h.settings.ai_profile(AiTask.VOICE_TRANSCRIBE).budget_weight
    assert h.budget.windows[h.student.user_id].used == 60 * weight


async def test_a_too_large_recording_is_refused_before_the_model(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: over the byte cap is a 422 problem, nothing is sent."""
    h, client = api
    big = ("big.ogg", b"0" * (MAX_BYTES + 1), "audio/ogg")

    response = await post(client, big)

    assert response.status_code == 422
    assert response.json()["type"] == "ai/voice-too-large"
    assert h.llm.requests == []


async def test_the_byte_cap_is_about_two_minutes_of_speech(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: the cap is 1 MB, enough for 120 s of low-bitrate speech."""
    assert MAX_BYTES == 1024 * 1024
    assert MAX_SECONDS == 120


async def test_an_oversized_recording_is_refused_whatever_duration_is_claimed(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: duration is client-reported, so the byte cap alone bounds the cost."""
    h, client = api
    big = ("big.ogg", b"0" * (MAX_BYTES + 1), "audio/ogg")

    for claimed_ms in (1, 4000, MAX_SECONDS * 1000):
        response = await post(client, big, duration_ms=claimed_ms)
        assert response.status_code == 422, claimed_ms
        assert response.json()["type"] == "ai/voice-too-large"
    assert h.llm.requests == []


async def test_a_long_recording_or_an_unknown_format_is_refused(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: the duration cap and the audio formats are checked up front."""
    h, client = api

    long = await post(client, OGG, duration_ms=MAX_SECONDS * 1000 + 1)
    text = await post(client, ("notes.txt", b"hi", "text/plain"))

    assert long.json()["type"] == "ai/voice-too-long"
    assert text.json()["type"] == "ai/voice-format"
    assert h.llm.requests == []


@pytest.mark.parametrize("content_type", ["audio/webm;codecs=opus", "audio/webm"])
async def test_browser_recordings_are_sent_in_their_format(
    api: tuple[AiHarness, AsyncClient], content_type: str
) -> None:
    """AI voice: the MediaRecorder format (WebM with codecs) reaches the model."""
    h, client = api
    h.llm.push(text_reply("ok"))

    clip = ("clip", b"\x1aE\xdf\xa3" + b"\x00" * 64, content_type)

    response = await post(client, clip)

    assert response.status_code == 200, response.text
    parts = h.llm.requests[-1]["messages"][0]["content"]
    assert parts[1]["input_audio"]["format"] == "webm"


async def test_a_pdf_declared_as_audio_is_refused_before_the_model(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: the bytes decide. A PDF labelled audio/ogg is a 422, no model call."""
    h, client = api

    response = await post(client, ("clip.ogg", b"%PDF-1.7 body", "audio/ogg"))

    assert response.status_code == 422
    assert response.json()["type"] == "ai/voice-format"
    assert h.llm.requests == []


async def test_the_model_gets_the_language_hint_and_the_verbatim_rule(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: the prompt names the student's language and forbids invented words."""
    h, client = api
    h.llm.push(text_reply("ok"))

    await post(client, OGG)

    sent = h.llm.requests[-1]
    assert "verbatim" in sent["system"]
    assert "never invent" in sent["system"].lower()
    # The harness student's locale is English (the identity fake's default).
    assert "English" in sent["messages"][0]["content"][0]["text"]


async def test_recordings_are_rate_limited_per_student(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI voice: the per-minute cap answers 429 once it is used up."""
    _, client = api
    for _ in range(RATE_PER_MINUTE):
        assert (await post(client, OGG)).status_code == 200

    limited = await post(client, OGG)

    assert limited.status_code == 429
