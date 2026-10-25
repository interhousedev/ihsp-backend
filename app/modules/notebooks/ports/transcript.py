"""Port: the spoken-text transcript of a YouTube video (URL sources)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

NO_TRANSCRIPT: Final = "no_transcript"  # the video has no transcript in the languages
TRANSCRIPTS_DISABLED: Final = "transcripts_disabled"  # the owner turned them off
VIDEO_UNAVAILABLE: Final = "video_unavailable"  # private, removed, age-gated, ...
PROVIDER_ERROR: Final = "provider_error"  # network, blocking, unparsable answer

# Codes that mean "this video has no text to read", not "the provider is down".
NO_TRANSCRIPT_CODES: Final = frozenset({NO_TRANSCRIPT, TRANSCRIPTS_DISABLED})


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One line of speech: seconds from the start, and the text."""

    start: float
    text: str


@dataclass(frozen=True, slots=True)
class VideoTranscript:
    """The transcript of a video in one language."""

    video_id: str
    language_code: str
    generated: bool  # True for automatic captions
    segments: tuple[TranscriptSegment, ...]


class TranscriptError(Exception):
    """The transcript cannot be had; `code` is one of the codes of this module."""

    def __init__(self, code: str) -> None:
        """Keep the machine code."""
        super().__init__(code)
        self.code = code


class TranscriptProvider(Protocol):
    """Fetches the transcript of a video, preferring the first language given."""

    async def fetch(self, video_id: str, languages: Sequence[str]) -> VideoTranscript:
        """Return the transcript; raise `TranscriptError` with a code of this module."""
        ...
