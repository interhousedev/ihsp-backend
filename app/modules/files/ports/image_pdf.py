"""Putting photos into one PDF."""

from collections.abc import Sequence
from typing import Protocol


class ImagePdfBuilder(Protocol):
    """Writes a PDF with one page per image (blocking: run it in a thread)."""

    def build(self, images: Sequence[bytes]) -> bytes:
        """Return the PDF of 1 or more JPEG/PNG images, one page each, in order.

        Raises ``ImageNotSupportedError`` for any image that is not a plain JPEG or
        PNG that can be embedded without decoding.
        """
        ...
