"""TranscriptProvider for the notebooks tests: transcripts by video id."""

from collections.abc import Sequence

from app.modules.notebooks.ports.transcript import (
    NO_TRANSCRIPT,
    TranscriptError,
    TranscriptSegment,
    VideoTranscript,
)


class FakeTranscriptProvider:
    """Serves the transcripts it was given; a video can be set to fail with a code."""

    def __init__(self) -> None:
        """Start with no videos."""
        self.videos: dict[str, VideoTranscript] = {}
        self.failures: dict[str, str] = {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def add_video(
        self,
        video_id: str,
        lines: Sequence[tuple[float, str]],
        *,
        language_code: str = "en",
        generated: bool = True,
    ) -> None:
        """Serve a transcript made of (seconds, text) lines."""
        segments = tuple(TranscriptSegment(start, text) for start, text in lines)
        self.videos[video_id] = VideoTranscript(
            video_id, language_code, generated, segments
        )

    def fail(self, video_id: str, code: str = NO_TRANSCRIPT) -> None:
        """Make the fetch of a video raise ``TranscriptError(code)``."""
        self.failures[video_id] = code

    async def fetch(self, video_id: str, languages: Sequence[str]) -> VideoTranscript:
        """Return the transcript or raise like the real provider."""
        self.calls.append((video_id, tuple(languages)))
        if video_id in self.failures:
            raise TranscriptError(self.failures[video_id])
        if video_id not in self.videos:
            raise TranscriptError(NO_TRANSCRIPT)
        return self.videos[video_id]
