"""The caption provider: language choice and error codes, with the library faked."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from app.modules.notebooks.infrastructure import youtube_transcript
from app.modules.notebooks.infrastructure.youtube_transcript import (
    YouTubeTranscriptProvider,
)
from app.modules.notebooks.ports.transcript import (
    NO_TRANSCRIPT,
    PROVIDER_ERROR,
    TRANSCRIPTS_DISABLED,
    VIDEO_UNAVAILABLE,
    TranscriptError,
)

import pytest
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

ID = "dQw4w9WgXcQ"


class FakeTranscript:
    """A listed transcript: language, generated flag, snippets when fetched."""

    def __init__(self, code: str, *, generated: bool) -> None:
        self.language_code = code
        self.is_generated = generated

    def fetch(self) -> list[Any]:
        return [SimpleNamespace(text=f"in {self.language_code}", start=1.5)]


class FakeList:
    """Transcripts by language; `find_transcript` misses like the library does."""

    def __init__(self, transcripts: list[FakeTranscript]) -> None:
        self.transcripts = transcripts

    def __iter__(self) -> Iterator[FakeTranscript]:
        return iter(self.transcripts)

    def find_transcript(self, codes: Any) -> FakeTranscript:
        for code in codes:
            for transcript in self.transcripts:
                if transcript.language_code == code:
                    return transcript
        raise _Missing(ID, list(codes), self)


class _Missing(NoTranscriptFound):
    """The library's miss, without its message builder."""

    def __init__(self, video_id: str, codes: list[str], listed: Any) -> None:
        Exception.__init__(self, video_id)


def fake_api(monkeypatch: pytest.MonkeyPatch, listing: Any) -> None:
    """Make `YouTubeTranscriptApi().list()` return `listing` (or raise it)."""

    class Api:
        def list(self, video_id: str) -> Any:
            if isinstance(listing, Exception):
                raise listing
            return listing

    monkeypatch.setattr(youtube_transcript, "YouTubeTranscriptApi", Api)


async def test_the_first_preferred_language_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uz beats ru and en; a manual transcript is looked up before generated ones."""
    listing = FakeList(
        [FakeTranscript("en", generated=False), FakeTranscript("ru", generated=True)]
    )
    fake_api(monkeypatch, listing)

    got = await YouTubeTranscriptProvider().fetch(ID, ("uz", "ru", "en"))

    assert (got.language_code, got.generated) == ("ru", True)
    assert [(s.start, s.text) for s in got.segments] == [(1.5, "in ru")]


async def test_any_language_is_taken_without_a_preferred_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a German transcript: it is read rather than failing."""
    fake_api(monkeypatch, FakeList([FakeTranscript("de", generated=False)]))

    got = await YouTubeTranscriptProvider().fetch(ID, ("uz", "ru", "en"))

    assert got.language_code == "de"


async def test_no_transcripts_at_all_is_no_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty list of transcripts."""
    fake_api(monkeypatch, FakeList([]))

    with pytest.raises(TranscriptError) as caught:
        await YouTubeTranscriptProvider().fetch(ID, ("en",))
    assert caught.value.code == NO_TRANSCRIPT


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TranscriptsDisabled(ID), TRANSCRIPTS_DISABLED),
        (VideoUnavailable(ID), VIDEO_UNAVAILABLE),
        (RuntimeError("network down"), PROVIDER_ERROR),
    ],
)
async def test_library_errors_become_codes(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    """Disabled, unavailable and any other fault map to their codes."""
    fake_api(monkeypatch, error)

    with pytest.raises(TranscriptError) as caught:
        await YouTubeTranscriptProvider().fetch(ID, ("en",))
    assert caught.value.code == code
