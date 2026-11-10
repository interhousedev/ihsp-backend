"""Read-time handling of the stored pictures of a slide deck.

The deck keeps only `image.file_id`; the presigned URL is made when a deck is read and
the bytes are read when a deck is exported.
"""

from typing import Any
from uuid import UUID

from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi

URL_TTL_SECONDS = 3600


def _image_refs(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The `image` dicts of the slides that have a file id."""
    slides = (content or {}).get("slides")
    if not isinstance(slides, list):
        return []
    refs: list[dict[str, Any]] = []
    for slide in slides:
        image = slide.get("image") if isinstance(slide, dict) else None
        if isinstance(image, dict) and image.get("file_id"):
            refs.append(image)
    return refs


def _file_id(image: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(image["file_id"]))
    except ValueError:
        return None


async def sign_images(
    files: FilesApi | None, content: dict[str, Any] | None
) -> dict[str, Any] | None:
    """A copy of the deck whose images carry a presigned `url`.

    A failed image has none.
    """
    if files is None or not content or not _image_refs(content):
        return content
    slides: list[Any] = []
    for slide in content["slides"]:
        image = slide.get("image") if isinstance(slide, dict) else None
        file_id = _file_id(image) if isinstance(image, dict) else None
        if isinstance(image, dict) and file_id is not None:
            try:
                url = await files.download_url(
                    file_id, inline=True, ttl_seconds=URL_TTL_SECONDS
                )
            except BaseError:
                slides.append(slide)
                continue
            slide = {**slide, "image": {**image, "url": url}}
        slides.append(slide)
    return {**content, "slides": slides}


async def load_image_bytes(
    files: FilesApi | None, content: dict[str, Any] | None
) -> dict[str, bytes]:
    """The content of every stored picture of the deck by file id (missing: skipped)."""
    found: dict[str, bytes] = {}
    if files is None:
        return found
    for image in _image_refs(content):
        key = str(image["file_id"])
        file_id = _file_id(image)
        if key in found or file_id is None:
            continue
        try:
            found[key] = await files.read_bytes(file_id)
        except BaseError:
            continue
    return found
