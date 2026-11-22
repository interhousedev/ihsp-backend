"""Voice through OpenRouter: transcriptions and speech, never stored.

The audio goes in the request body and is dropped with it; providers that keep or
train on data are excluded (`data_collection: deny`). Revoked AI access is refused
before the call, and every call is written to the usage ledger.
"""

import base64
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.voice import silence, wav
from app.shared.ai_access import scope_of
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiAccessRevokedError, AiProviderError
from app.shared.limits import LimitsProvider

import httpx

FAKE_TRANSCRIPT = "Sample voice answer transcribed by the fake model."
VOICE = "Kore"
_PRIVACY = {"data_collection": "deny"}


class _Pending(Protocol):
    async def finish(
        self, usage: Mapping[str, Any] | None = None, *, error: str | None = None
    ) -> Any:
        """Close the usage record."""
        ...


class Ledger(Protocol):
    """The usage recorder (`UsageRecorder.begin`)."""

    async def begin(self, *, model: str, task: str | None) -> _Pending:
        """Start one usage record."""
        ...


class OpenRouterVoice:
    """`POST /audio/transcriptions` and `POST /audio/speech`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        app_url: str,
        app_title: str,
        timeout_seconds: float,
        models: Mapping[AiTask, str],
        limits: LimitsProvider,
        ledger: Ledger | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the client; pass `client` in tests."""
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0)
        )
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": app_url,
            "X-OpenRouter-Title": app_title,
            "X-Title": app_title,
        }
        self._models = models
        self._limits = limits
        self._ledger = ledger

    async def _post(
        self, user_id: UUID, task: AiTask, path: str, body: dict[str, Any]
    ) -> httpx.Response:
        if (await self._limits.ai_access(user_id)).blocks(scope_of(task)):
            raise AiAccessRevokedError(params={"scope": scope_of(task)})
        model = self._models[task]
        pending = (
            await self._ledger.begin(model=model, task=task) if self._ledger else None
        )
        try:
            reply = await self._client.post(
                f"{self._base}{path}",
                json={"model": model, **body, "provider": _PRIVACY},
                headers=self._headers,
            )
            reply.raise_for_status()
        except httpx.HTTPError as exc:
            if pending is not None:
                await pending.finish(error=type(exc).__name__[:64])
            raise AiProviderError() from exc
        if pending is not None:
            usage = None
            if reply.headers.get("content-type", "").startswith("application/json"):
                usage = reply.json().get("usage")
            await pending.finish(usage if isinstance(usage, dict) else None)
        return reply

    async def transcribe(
        self, user_id: UUID, data: bytes, fmt: str, language: str
    ) -> str:
        """The text of the recording."""
        reply = await self._post(
            user_id,
            AiTask.ADMIT_VOICE_TRANSCRIBE,
            "/audio/transcriptions",
            {
                "input_audio": {
                    "data": base64.b64encode(data).decode("ascii"),
                    "format": fmt,
                },
                "language": language,
            },
        )
        return str(reply.json().get("text") or "").strip()

    async def speak(self, user_id: UUID, text: str, locale: str) -> bytes:
        """A WAV of the text (the model answers raw 24 kHz PCM)."""
        reply = await self._post(
            user_id,
            AiTask.ADMIT_QUESTION_SPEECH,
            "/audio/speech",
            {"input": text, "voice": VOICE, "response_format": "pcm"},
        )
        return wav(reply.content)


class FakeVoice:
    """Fake mode: a fixed transcript and a short silence; no key, no network."""

    async def transcribe(
        self, user_id: UUID, data: bytes, fmt: str, language: str
    ) -> str:
        """The fixed transcript."""
        return FAKE_TRANSCRIPT

    async def speak(self, user_id: UUID, text: str, locale: str) -> bytes:
        """A fifth of a second of silence."""
        return silence()


def make_voice(
    settings: Any, limits: LimitsProvider, ledger: Ledger | None
) -> OpenRouterVoice | FakeVoice | None:
    """The adapter for the settings; None when real mode has no key."""
    config = settings.openrouter
    if config.mode == "fake":
        return FakeVoice()
    if config.api_key is None:
        return None
    return OpenRouterVoice(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        app_url=config.app_url,
        app_title=config.app_title,
        timeout_seconds=config.timeout_seconds,
        models={
            task: settings.ai.profile(task).model
            for task in (AiTask.ADMIT_VOICE_TRANSCRIBE, AiTask.ADMIT_QUESTION_SPEECH)
        },
        limits=limits,
        ledger=ledger,
    )
