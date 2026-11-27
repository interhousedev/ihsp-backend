"""Text-to-speech contract (provider: an adapter of the media module)."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WordTiming:
    """Word boundary reported by a provider (milliseconds)."""

    word: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """One synthesized utterance."""

    audio: bytes
    duration_ms: int
    word_timings: tuple[WordTiming, ...] = ()
    chars_billed: int = 0


class SpeechSynthesizer(Protocol):
    """Turns text into speech."""

    async def synthesize(
        self, *, text: str, language: str, voice_id: str, speed: float = 1.0
    ) -> SynthesisResult:
        """Synthesize `text` in `language` with the voice."""
        ...
