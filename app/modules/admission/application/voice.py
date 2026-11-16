"""Voice answers and read-aloud questions.

A recording is checked (size, length, format from its bytes), sent once to the
speech model and dropped; only the returned text reaches the caller. The privacy
policy discloses this. Reading aloud speaks only stored question text.
Both count against one daily soft limit; sizes and lengths apply to everyone.
"""

from typing import Final
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review import require_ai_consent
from app.modules.admission.domain.career import LOCALES, localized
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    VoiceFormatError,
    VoiceTooLargeError,
    VoiceTooLongError,
)
from app.modules.admission.domain.voice import (
    FORMATS,
    RATE_PER_MINUTE,
    RATE_WINDOW_SECONDS,
    sniff,
)
from app.modules.admission.ports.ai import QuotaOf
from app.modules.admission.ports.consent import PurposeConsents
from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.admission.ports.voice import VoiceAi
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter

_DAY: Final = 24 * 3600
_MB: Final = 1024 * 1024


class VoiceService:
    """Transcribe a voice answer; read a question aloud."""

    def __init__(
        self,
        uow_factory: UowFactory,
        voice: VoiceAi,
        limiter: RateLimiter,
        daily_limit: QuotaOf,
        limits: LimitsProvider,
        consents: PurposeConsents,
    ) -> None:
        """Keep the collaborators; caps are read per call from the limits."""
        self._uow = uow_factory
        self._voice = voice
        self._limiter = limiter
        self._daily = daily_limit
        self._limits = limits
        self._consents = consents

    async def max_bytes(self, user_id: UUID) -> int:
        """The largest recording accepted now (the route reads at most this)."""
        return int((await self._limits.for_user(user_id)).admit_voice_max_bytes)

    async def _count(self, user_id: UUID) -> None:
        await self._limiter.hit(
            f"admission:voice:minute:{user_id}",
            limit=RATE_PER_MINUTE,
            window_seconds=RATE_WINDOW_SECONDS,
        )
        limit = await self._daily(user_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:voice:{user_id}", limit=limit, window_seconds=_DAY
            )

    async def transcribe(
        self, ctx: AdmissionContext, data: bytes, seconds: float, locale: str
    ) -> str:
        """The text of the recording; the bytes are not kept anywhere."""
        await require_ai_consent(self._consents, ctx.user_id)
        caps = await self._limits.for_user(ctx.user_id)
        if len(data) > int(caps.admit_voice_max_bytes):
            raise VoiceTooLargeError(
                params={"max_mb": round(caps.admit_voice_max_bytes / _MB, 1)}
            )
        if seconds > int(caps.admit_voice_max_seconds):
            raise VoiceTooLongError(
                params={"max_seconds": caps.admit_voice_max_seconds}
            )
        fmt = sniff(data[:16])
        if fmt is None:
            raise VoiceFormatError(params={"formats": ", ".join(FORMATS)})
        await self._count(ctx.user_id)
        language = locale if locale in LOCALES else "en"
        return await self._voice.transcribe(ctx.user_id, data, fmt, language)

    async def speak(
        self, ctx: AdmissionContext, question_id: UUID, locale: str
    ) -> bytes:
        """A WAV of the question's text in the locale."""
        async with self._uow() as uow:
            question = await uow.career.get_question(question_id)
        if question is None or not question.active:
            raise AdmissionNotFoundError(params={"object": "career_question"})
        caps = await self._limits.for_user(ctx.user_id)
        text = localized(question.prompt, locale)[: int(caps.admit_speech_max_chars)]
        await self._count(ctx.user_id)
        return await self._voice.speak(ctx.user_id, text, locale)
