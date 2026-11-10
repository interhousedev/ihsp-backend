"""Deterministic stand-in engine: the embedding is a hash of the bytes.

The same bytes always give the same face, so tests and local runs can enrol and
recognise without models. The markers `NOFACE` and `TWOFACES` inside an image
simulate a photo without a face and with two.
"""

import hashlib

from app.modules.faces.domain.errors import MultipleFacesError

DIMENSIONS = 128


class FakeFaceEngine:
    """Hash-based embeddings."""

    async def embed(self, image: bytes) -> list[float] | None:
        """Return a unit-free embedding derived from the bytes."""
        if b"NOFACE" in image:
            return None
        if b"TWOFACES" in image:
            raise MultipleFacesError()
        out: list[float] = []
        counter = 0
        while len(out) < DIMENSIONS:
            block = hashlib.sha256(image + counter.to_bytes(4, "big")).digest()
            out.extend(b / 127.5 - 1.0 for b in block)
            counter += 1
        return out[:DIMENSIONS]
