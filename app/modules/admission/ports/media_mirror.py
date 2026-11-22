"""Port: copy an external image into our own storage."""

from typing import Protocol


class MediaMirror(Protocol):
    """Fetches an external image and returns its public storage URL."""

    own_prefix: str
    """URLs starting with this are already ours."""

    async def mirror(self, url: str) -> str:
        """Return the storage URL of the image; own URLs come back unchanged.

        Raises `MediaUnreachableError` when it cannot be fetched or is not an image.
        """
        ...
