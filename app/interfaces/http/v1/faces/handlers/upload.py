"""Reading an uploaded image."""

from app.modules.faces.domain.image import MAX_IMAGE_BYTES

from fastapi import UploadFile


async def read_image(file: UploadFile) -> bytes:
    """Read the upload; one byte past the limit is enough to refuse it."""
    return await file.read(MAX_IMAGE_BYTES + 1)
