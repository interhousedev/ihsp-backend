"""Audio out of a video, for transcription: an ffmpeg child process with hard bounds.

The video goes in on stdin, mono low-bitrate Ogg Opus comes out on stdout. There is
no shell, the child is killed after a timeout, the duration is capped with `-t` and
the output with `-fs` (ffmpeg stops there). The image installs ffmpeg (Dockerfile).
"""

import asyncio
from collections.abc import Sequence
from typing import Final

from app.modules.ai.domain.errors import VoiceTooLargeError
from app.modules.ai.domain.voice import MAX_BYTES, MAX_SECONDS

MAX_VIDEO_BYTES: Final = 10 * 1024 * 1024  # the video that may go to ffmpeg
EXTRACT_TIMEOUT_SECONDS: Final = 30.0
MAX_CONCURRENT_EXTRACTS: Final = 2  # ffmpeg children per process at once
EXTRACT_SLOTS = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTS)
FFMPEG: Final[tuple[str, ...]] = ("ffmpeg",)
AUDIO_BITRATE: Final = "12k"
MEGABYTE: Final = 1024 * 1024


class ExtractError(Exception):
    """ffmpeg is missing, failed, or did not finish in time."""


def build_argv(command: Sequence[str], *, max_bytes: int, seconds: int) -> list[str]:
    """The full argv: audio only, mono, low bitrate, bounded in length and size."""
    return [
        *command,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-vn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        AUDIO_BITRATE,
        "-t",
        str(seconds),
        "-fs",
        str(max_bytes),
        "-f",
        "ogg",
        "pipe:1",
    ]


async def extract_audio(
    data: bytes,
    *,
    command: Sequence[str] = FFMPEG,
    max_bytes: int = MAX_BYTES,
    seconds: int = MAX_SECONDS,
    timeout: float = EXTRACT_TIMEOUT_SECONDS,
) -> bytes:
    """The audio track of a video as Ogg Opus bytes.

    Raises:
        ExtractError: ffmpeg is missing, failed, produced nothing, or timed out.
        VoiceTooLargeError: the audio is over `max_bytes`.
    """
    argv = build_argv(command, max_bytes=max_bytes, seconds=seconds)
    async with EXTRACT_SLOTS:  # a video waits for a free ffmpeg slot
        output = await _run(argv, data, timeout)
    if len(output) > max_bytes:
        raise VoiceTooLargeError(params={"max_mb": max_bytes // MEGABYTE})
    return output


async def _run(argv: list[str], data: bytes, timeout: float) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        raise ExtractError("ffmpeg is not available") from error
    try:
        output, _ = await asyncio.wait_for(process.communicate(input=data), timeout)
    except TimeoutError as error:
        await _kill(process)
        raise ExtractError("audio extraction timed out") from error
    if process.returncode != 0 or not output:
        raise ExtractError("audio extraction failed")
    return output


async def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass
    await process.wait()
