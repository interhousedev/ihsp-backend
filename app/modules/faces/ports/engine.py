"""Port: turns a photo into a face embedding."""

from typing import Protocol


class FaceEngine(Protocol):
    """Face detection and recognition."""

    async def embed(self, image: bytes) -> list[float] | None:
        """Return the embedding of the one face in the image.

        Returns None when there is no face and raises `MultipleFacesError` when
        there are several.
        """
        ...


class ImageSniffer(Protocol):
    """Names the content type of the first bytes of an upload."""

    async def sniff(self, head: bytes) -> str:
        """Return the MIME type from the bytes alone."""
        ...
