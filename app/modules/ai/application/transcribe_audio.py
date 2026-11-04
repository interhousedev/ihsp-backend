"""Use case: speech to text for the chat input (`POST /v1/ai/transcriptions`).

The recording goes to the voice model once and is not stored anywhere. It is counted
in the student's token budget and in the usage ledger like any other model call.
"""

import base64
from typing import Final, Protocol

from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.locale import DEFAULT_LOCALE, LocaleResolver
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.errors import (
    AiLimitReachedError,
    VoiceFormatError,
    VoiceTooLargeError,
    VoiceTooLongError,
)
from app.modules.ai.domain.voice import (
    MAX_BYTES,
    MAX_OUTPUT_TOKENS,
    MAX_SECONDS,
    RATE_PER_MINUTE,
    RATE_WINDOW_SECONDS,
    SNIFF_BYTES,
    SNIFFED_FORMATS,
    sniffed_format,
)
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.rate_limit import RateLimiter

SYSTEM: Final = (
    "Transcribe the student's short voice message. Return only the words spoken, "
    "verbatim, without commentary. Never invent words; if there is no speech, "
    "return an empty string."
)
USER: Final = (
    "Transcribe the attached recording. The speaker most likely uses {language}."
)
LANGUAGES: Final[dict[str, str]] = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
RATE_KEY: Final = "ai-voice:{user_id}"


class AudioSniffer(Protocol):
    """Names the real MIME type of a file from its first bytes (libmagic)."""

    async def sniff(self, head: bytes) -> str:
        """Return the detected MIME type."""
        ...


class TranscribeAudio:
    """Turns one short recording into text; nothing is stored."""

    def __init__(
        self,
        *,
        llm: LlmGateway,
        budget: BudgetService,
        rate_limiter: RateLimiter,
        settings: Settings,
        locale: LocaleResolver,
        sniffer: AudioSniffer,
    ) -> None:
        """Store the collaborators; `sniffer` names the real type of the bytes."""
        self.llm = llm
        self.budget = budget
        self.rate_limiter = rate_limiter
        self.settings = settings
        self.locale = locale
        self.sniffer = sniffer

    async def precheck(self, actor: Actor) -> None:
        """Refuse before any download: revoked chat access or the minute's limit spent.

        Reads the counters only; `execute` counts the recording.
        """
        await self.budget.require_access(actor.user_id, "chat")
        await self.rate_limiter.check(
            RATE_KEY.format(user_id=actor.user_id), limit=RATE_PER_MINUTE
        )

    async def execute(self, actor: Actor, *, data: bytes, duration_ms: int) -> str:
        """Return the transcript of the recording.

        The format is the one libmagic finds in the bytes, never a declared type.

        Raises:
            VoiceTooLargeError: More than `MAX_BYTES` bytes.
            VoiceTooLongError: The reported duration is over `MAX_SECONDS`.
            VoiceFormatError: The bytes are not an audio file the model reads.
            AiAccessRevokedError: Administration revoked the chat scope.
            AiLimitReachedError: The student's token budget does not cover it.
            RateLimitedError: More than `RATE_PER_MINUTE` recordings a minute.
        """
        if len(data) > MAX_BYTES:
            raise VoiceTooLargeError(params={"max_mb": MAX_BYTES // (1024 * 1024)})
        if duration_ms > MAX_SECONDS * 1000:
            raise VoiceTooLongError(params={"max_seconds": MAX_SECONDS})
        fmt = sniffed_format(await self.sniffer.sniff(data[:SNIFF_BYTES]))
        if fmt is None:
            formats = sorted(set(SNIFFED_FORMATS.values()))
            raise VoiceFormatError(params={"formats": ", ".join(formats)})
        await self.budget.require_access(actor.user_id, "chat")
        await self.rate_limiter.hit(
            RATE_KEY.format(user_id=actor.user_id),
            limit=RATE_PER_MINUTE,
            window_seconds=RATE_WINDOW_SECONDS,
        )
        profile = self.settings.ai_profile(AiTask.VOICE_TRANSCRIBE)
        estimate = (len(data) // 1000 + MAX_OUTPUT_TOKENS) * profile.budget_weight
        hit = await self.budget.check(actor.user_id, Assistant.STUDENT, estimate)
        if hit is not None:
            raise AiLimitReachedError(params=hit.params())
        locale = await self.locale.locale_of(actor.user_id)
        language = LANGUAGES.get(locale, LANGUAGES[DEFAULT_LOCALE])
        encoded = base64.b64encode(data).decode("ascii")
        response = await self.llm.complete(
            model=profile.model,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER.format(language=language)},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded, "format": fmt},
                        },
                    ],
                }
            ],
            tools=[],
            max_tokens=profile.output_tokens(MAX_OUTPUT_TOKENS),
            provider=profile.provider(),
            tuning=profile.tuning,
        )
        usage = response.get("usage") or {}
        tokens = int(usage.get("input", 0)) + int(usage.get("output", 0))
        await self.budget.add(
            actor.user_id, tokens * profile.budget_weight, Assistant.STUDENT
        )
        return str(response.get("text") or "").strip()
