"""Bot downloads: a file Telegram reports as too large is refused before download."""

from typing import Any

from app.interfaces.bot.assistant.media import MAX_FILE_BYTES, download_capped
from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    FileTooLargeError,
)

import pytest


class RecordingBot:
    """Counts the downloads; writes a fixed payload into the destination."""

    def __init__(self, payload: bytes = b"data") -> None:
        self.payload = payload
        self.downloads: list[str] = []

    async def download(self, file_id: str, destination: Any) -> None:
        self.downloads.append(file_id)
        destination.write(self.payload)


async def test_a_file_reported_over_the_limit_is_refused_before_download() -> None:
    bot = RecordingBot()
    with pytest.raises(FileTooLargeError):
        await download_capped(
            bot,  # type: ignore[arg-type]
            "f1",
            size=MAX_FILE_BYTES + 1,
        )
    assert bot.downloads == []


async def test_a_file_within_the_limit_is_downloaded() -> None:
    bot = RecordingBot(b"abc")
    data = await download_capped(bot, "f2", size=3)  # type: ignore[arg-type]
    assert data == b"abc" and bot.downloads == ["f2"]


async def test_an_unknown_size_is_still_checked_after_download() -> None:
    bot = RecordingBot(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(FileTooLargeError):
        await download_capped(bot, "f3")  # type: ignore[arg-type]
    assert bot.downloads == ["f3"]
