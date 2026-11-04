"""Audio extraction from a video: bounded, no shell, killed on timeout.

The extractor runs a command given as argv (no shell). Tests use the Python
interpreter as a stand-in command, so no ffmpeg is needed to run them.
"""

import asyncio
import sys

from app.interfaces.bot.assistant import video
from app.interfaces.bot.assistant.video import (
    ExtractError,
    build_argv,
    extract_audio,
)
from app.modules.ai.domain.errors import VoiceTooLargeError
from app.modules.ai.domain.voice import MAX_SECONDS

import pytest

PY = sys.executable


def test_the_argv_is_a_list_that_keeps_only_audio_and_bounds_it() -> None:
    argv = build_argv(["ffmpeg"], max_bytes=1000, seconds=MAX_SECONDS)
    assert all(isinstance(part, str) for part in argv)
    assert argv[0] == "ffmpeg"
    for flag in ("-vn", "-nostdin"):
        assert flag in argv
    assert argv[argv.index("-ac") + 1] == "1"  # mono
    assert argv[argv.index("-b:a") + 1].endswith("k")  # low bitrate
    assert argv[argv.index("-fs") + 1] == "1000"  # output size cap
    assert argv[argv.index("-t") + 1] == str(MAX_SECONDS)  # duration cap
    assert argv[-1] == "pipe:1"


async def test_the_video_goes_in_on_stdin_and_the_audio_comes_out_on_stdout() -> None:
    echo = [PY, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
    audio = await extract_audio(b"video-bytes", command=echo, max_bytes=1000)
    assert audio == b"video-bytes"


async def test_output_over_the_audio_cap_is_refused() -> None:
    echo = [PY, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
    with pytest.raises(VoiceTooLargeError):
        await extract_audio(b"x" * 2000, command=echo, max_bytes=1000)


async def test_a_failing_extractor_is_an_extract_error() -> None:
    failing = [PY, "-c", "import sys; sys.exit(1)"]
    with pytest.raises(ExtractError):
        await extract_audio(b"v", command=failing, max_bytes=1000)


async def test_a_missing_binary_is_an_extract_error() -> None:
    with pytest.raises(ExtractError):
        await extract_audio(
            b"v", command=["/nonexistent/ffmpeg-binary"], max_bytes=1000
        )


async def test_a_hanging_extractor_is_killed_after_the_timeout() -> None:
    sleeper = [PY, "-c", "import time; time.sleep(60)"]
    with pytest.raises(ExtractError):
        await extract_audio(b"v", command=sleeper, max_bytes=1000, timeout=0.3)


async def test_ffmpeg_runs_are_capped_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run waits for a free slot: no more ffmpeg children than the cap at once."""
    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(video, "EXTRACT_SLOTS", slots)
    echo = [PY, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
    await slots.acquire()  # the one slot is taken by another recording
    waiting = asyncio.create_task(extract_audio(b"video", command=echo, max_bytes=1000))
    await asyncio.sleep(0.2)
    assert not waiting.done()  # it has not started ffmpeg yet
    slots.release()
    assert await waiting == b"video"


def test_the_cap_is_small() -> None:
    assert 1 <= video.MAX_CONCURRENT_EXTRACTS <= 4
