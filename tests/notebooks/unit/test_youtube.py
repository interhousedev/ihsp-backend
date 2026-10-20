"""YouTube links: the video id of a URL, and the rendering of a transcript."""

from app.modules.notebooks.domain.youtube import render_transcript, youtube_video_id

import pytest

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}&t=42s",
        f"https://m.youtube.com/watch?feature=share&v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=abc",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://www.youtube.com/embed/{ID}?start=5",
        f"https://www.youtube.com/live/{ID}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}",
        f"https://www.youtube.com/v/{ID}",
    ],
)
def test_video_urls_give_their_id(url: str) -> None:
    """Every supported form of a YouTube link yields the 11-character id."""
    assert youtube_video_id(url) == ID


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ_extra",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/channel/UC123",
        "https://www.youtube.com/shorts/",
        "https://youtu.be/",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
        "not a url",
        "http://[::1",
    ],
)
def test_other_urls_give_no_id(url: str) -> None:
    """Pages that are not a video of YouTube have no id."""
    assert youtube_video_id(url) is None


def test_first_watch_id_wins_and_empty_v_is_none() -> None:
    """A repeated `v` takes the first value; an empty one is not an id."""
    assert youtube_video_id(f"https://youtube.com/watch?v={ID}&v=aaaaaaaaaaa") == ID
    assert youtube_video_id("https://youtube.com/watch?v=&t=3") is None


def test_transcript_lines_carry_their_clock_and_skip_blanks() -> None:
    """One `[m:ss]` line per segment; `[h:mm:ss]` from one hour on."""
    text = render_transcript(
        [
            (0.0, "Hello"),
            (5.9, "  two\nlines  "),
            (9.0, "   "),
            (65.2, "minute"),
            (3723.0, "late"),
        ]
    )
    assert text == "[0:00] Hello\n[0:05] two lines\n[1:05] minute\n[1:02:03] late"


def test_empty_transcript_renders_nothing() -> None:
    """No segments, or only blank ones, give an empty text."""
    assert render_transcript([]) == ""
    assert render_transcript([(1.0, " ")]) == ""
