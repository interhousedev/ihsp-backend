"""What kind of input a source is, and whether a model can read it (`MODALITIES`)."""

from collections.abc import Collection
from typing import Any, Final

from app.modules.notebooks.domain.entities import Source
from app.shared.ai_tasks import Modality

_BY_EXTENSION: Final[dict[str, Modality]] = {
    "pdf": "pdf",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "mp3": "audio",
    "wav": "audio",
    "m4a": "audio",
    "ogg": "audio",
    "mp4": "video",
    "mov": "video",
    "webm": "video",
    "mkv": "video",
}


def _from_name(name: str) -> Modality:
    """The modality of a file extension or content type; text when unknown."""
    lowered = name.lower()
    if lowered == "application/pdf":
        return "pdf"
    major = lowered.split("/", 1)[0]
    if major in ("image", "audio", "video"):
        return major  # type: ignore[return-value]
    return _BY_EXTENSION.get(lowered.rsplit(".", 1)[-1], "text")


def source_modality(source: Source) -> Modality:
    """The input kind of a source: from its stored content type or format, else name."""
    ref: dict[str, Any] = source.ref
    for key in ("content_type", "format"):
        value = ref.get(key)
        if isinstance(value, str) and value:
            found = _from_name(value)
            if found != "text":
                return found
    if source.kind.value in ("file", "lesson_resource"):
        return _from_name(source.title)
    return "text"


def readable_by(source: Source, modalities: Collection[str]) -> bool:
    """True when the model reads this source's input kind."""
    return source_modality(source) in modalities
