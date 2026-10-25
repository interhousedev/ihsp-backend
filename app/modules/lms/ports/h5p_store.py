"""Port: the object store that keeps unpacked H5P packages."""

from collections.abc import Sequence
from typing import Protocol


class H5PObjectStore(Protocol):
    """The subset of the files module's object storage the LMS uses (S3)."""

    async def get(self, key: str) -> bytes:
        """Return the object; raise when it does not exist."""
        ...

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write the object."""
        ...

    async def delete_many(self, keys: Sequence[str]) -> None:
        """Delete objects; missing keys are fine."""
        ...
