"""Content sniffing with libmagic (python-magic)."""

import asyncio
from collections.abc import Callable
from typing import Any


class MagicSniffer:
    """ContentSniffer over libmagic (system package: libmagic1 or brew libmagic)."""

    def __init__(self) -> None:
        """Load libmagic now so a missing system library fails at startup."""
        import magic  # noqa: PLC0415  (imported here: it needs a system library)

        self._from_buffer: Callable[..., Any] = magic.from_buffer

    async def sniff(self, head: bytes) -> str:
        """Return the MIME type of the first bytes of a file."""
        mime: str = await asyncio.to_thread(self._from_buffer, head, mime=True)
        return mime
