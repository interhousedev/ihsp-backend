"""Detection of the real type of a file from its first bytes."""

from typing import Protocol


class ContentSniffer(Protocol):
    """Looks at bytes, never trusts the client."""

    async def sniff(self, head: bytes) -> str:
        """Return the detected MIME type."""
        ...
