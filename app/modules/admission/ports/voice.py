"""Port: speech to text of a voice answer, and reading a question aloud."""

from typing import Protocol
from uuid import UUID


class VoiceAi(Protocol):
    """The speech models; audio passes through in memory and is never stored."""

    async def transcribe(
        self, user_id: UUID, data: bytes, fmt: str, language: str
    ) -> str:
        """Return the text of a recording in the given container format."""
        ...

    async def speak(self, user_id: UUID, text: str, locale: str) -> bytes:
        """Return a WAV recording of the text."""
        ...
