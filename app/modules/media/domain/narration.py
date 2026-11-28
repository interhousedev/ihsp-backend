"""Voice-over script: segments, validation, captions and timecodes."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.shared.base_error import ValidationFailedError


class NarrationInvalidError(ValidationFailedError):
    """The script cannot be voiced."""

    code = "media/narration-invalid"
    message_key = "media-narration-invalid"


@dataclass(frozen=True, slots=True)
class Segment:
    """One spoken piece of the script; the times are set once it is voiced."""

    id: str
    speaker: str
    text: str
    start_ms: int = 0
    end_ms: int = 0
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NarrationOptions:
    """How the script is voiced."""

    style: str
    length: str
    language: str
    voice_id: str
    speed: float = 1.0


_CYRILLIC = re.compile(r"[а-яёўқғҳА-ЯЁЎҚҒҲ]")
_LATIN = re.compile(r"[A-Za-z]")
_UZ_MARK = re.compile(
    r"[oOgG][ʻʼ'’`]|\b(?:va|bu|uchun|bilan|ham|shu|dars|bir|yoki|lekin)\b",
    re.IGNORECASE,
)
_EN_WORDS = re.compile(
    r"\b(?:the|is|are|and|of|to|we|this|that|with|today|hello)\b", re.IGNORECASE
)


def detect_language(text: str) -> str:
    """Guess "uz", "ru" or "en" from the script."""
    if len(_CYRILLIC.findall(text)) > len(_LATIN.findall(text)):
        return "ru"
    if _UZ_MARK.search(text) and not _EN_WORDS.search(text):
        return "uz"
    return "en"


def validate_script(
    segments: Sequence[Segment], *, language: str, max_chars: int
) -> None:
    """Refuse an empty, blank, over-long or wrong-language script."""
    if not segments:
        raise NarrationInvalidError(params={"reason": "empty"})
    if any(not s.text.strip() for s in segments):
        raise NarrationInvalidError(params={"reason": "blank"})
    full = " ".join(s.text for s in segments)
    if len(full) > max_chars:
        raise NarrationInvalidError(params={"reason": "too-long", "max": max_chars})
    detected = detect_language(full)
    # Latin uz text with no marker words reads like English: only a clear
    # mismatch fails.
    if detected != language and not (
        language == "uz" and detected == "en" and not _EN_WORDS.search(full)
    ):
        raise NarrationInvalidError(params={"reason": "language"})


def align_segments(
    segments: Sequence[Segment], durations_ms: Sequence[int]
) -> tuple[Segment, ...]:
    """Give the segments contiguous start/end times from their durations."""
    out: list[Segment] = []
    cursor = 0
    for segment, duration in zip(segments, durations_ms, strict=True):
        out.append(replace(segment, start_ms=cursor, end_ms=cursor + duration))
        cursor += duration
    return tuple(out)


def _vtt_time(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def build_vtt(segments: Sequence[Segment]) -> str:
    """Render WebVTT with one cue per segment."""
    cues = [
        f"{_vtt_time(s.start_ms)} --> {_vtt_time(s.end_ms)}\n{s.text}" for s in segments
    ]
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n"


def timecode(ms: int) -> str:
    """Format as "mm:ss" (minutes may exceed 59)."""
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes:02d}:{seconds:02d}"
