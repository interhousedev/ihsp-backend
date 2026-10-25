"""TranscriptProvider over `youtube_transcript_api` (captions of a YouTube video)."""

import asyncio
from collections.abc import Sequence

from app.modules.notebooks.ports.transcript import (
    NO_TRANSCRIPT,
    PROVIDER_ERROR,
    TRANSCRIPTS_DISABLED,
    VIDEO_UNAVAILABLE,
    TranscriptError,
    TranscriptSegment,
    VideoTranscript,
)

import structlog
from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    Transcript,
    TranscriptList,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)

log = structlog.get_logger(__name__)

UNAVAILABLE_ERRORS = (VideoUnavailable, VideoUnplayable, InvalidVideoId, AgeRestricted)


class YouTubeTranscriptProvider:
    """Reads captions with `YouTubeTranscriptApi`; blocking calls run in a thread."""

    async def fetch(self, video_id: str, languages: Sequence[str]) -> VideoTranscript:
        """The transcript in the first language available, else any language.

        Raises:
            TranscriptError: No transcript, disabled, unavailable or a provider fault.
        """
        try:
            return await asyncio.to_thread(_fetch_sync, video_id, tuple(languages))
        except TranscriptError:
            raise
        except TranscriptsDisabled as exc:
            raise TranscriptError(TRANSCRIPTS_DISABLED) from exc
        except NoTranscriptFound as exc:
            raise TranscriptError(NO_TRANSCRIPT) from exc
        except UNAVAILABLE_ERRORS as exc:
            raise TranscriptError(VIDEO_UNAVAILABLE) from exc
        except Exception as exc:  # network, blocking, unparsable: a provider fault
            log.info(
                "notebooks_transcript_provider_error",
                video_id=video_id,
                error=type(exc).__name__,
            )
            raise TranscriptError(PROVIDER_ERROR) from exc


def _fetch_sync(video_id: str, languages: tuple[str, ...]) -> VideoTranscript:
    """Blocking part of `fetch`: list the transcripts, pick one, read its segments."""
    transcripts = YouTubeTranscriptApi().list(video_id)
    transcript = pick_transcript(transcripts, languages)
    fetched = transcript.fetch()
    segments = tuple(
        TranscriptSegment(start=float(snippet.start), text=snippet.text)
        for snippet in fetched
    )
    return VideoTranscript(
        video_id=video_id,
        language_code=transcript.language_code,
        generated=transcript.is_generated,
        segments=segments,
    )


def pick_transcript(
    transcripts: TranscriptList, languages: Sequence[str]
) -> Transcript:
    """The transcript of the first language in `languages`, else the first one listed.

    Within a language a manual transcript wins over automatic captions (the library
    looks manual ones up first).

    Raises:
        TranscriptError: The video has no transcript at all (`no_transcript`).
    """
    for code in languages:
        try:
            return transcripts.find_transcript([code])
        except NoTranscriptFound:
            continue
    first = next(iter(transcripts), None)
    if first is None:
        raise TranscriptError(NO_TRANSCRIPT)
    return first
