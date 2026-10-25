"""In-memory H5P object store: tests and processes built without S3."""

from collections.abc import Sequence


class MemoryH5PStore:
    """A dict of objects; ``get`` raises KeyError for unknown keys."""

    def __init__(self) -> None:
        """Start empty."""
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def get(self, key: str) -> bytes:
        """Return the object."""
        return self.objects[key][0]

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write the object."""
        self.objects[key] = (data, content_type)

    async def delete_many(self, keys: Sequence[str]) -> None:
        """Delete objects; missing keys are fine."""
        for key in keys:
            self.objects.pop(key, None)
