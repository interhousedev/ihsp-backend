"""Deterministic speech and video adapters (the default mode; no provider keys)."""

from app.modules.media.domain.narration import Segment
from app.shared.contracts.speech import SynthesisResult, WordTiming


class FakeSpeech:
    """`SpeechSynthesizer`: 10 ms per character, bytes derived from the text."""

    async def synthesize(
        self, *, text: str, language: str, voice_id: str, speed: float = 1.0
    ) -> SynthesisResult:
        """Fake speech with word timings."""
        duration = max(1, int(len(text) * 10 / speed))
        words, cursor = [], 0
        for word in text.split():
            step = duration * len(word) // max(len(text), 1)
            words.append(WordTiming(word, cursor, cursor + step))
            cursor += step
        return SynthesisResult(
            audio=f"audio:{voice_id}:{text}".encode(),
            duration_ms=duration,
            word_timings=tuple(words),
            chars_billed=len(text),
        )


class FakeVideo:
    """`VideoRenderer`: fixed bytes per composition."""

    async def render(
        self,
        *,
        composition_hash: str,
        fmt: str,
        length_s: int,
        segments: tuple[Segment, ...],
        audio: bytes | None = None,
    ) -> bytes:
        """Fake mp4."""
        return b"mp4:" + composition_hash.encode()
