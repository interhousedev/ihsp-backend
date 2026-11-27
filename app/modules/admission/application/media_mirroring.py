"""Replace external logo and cover URLs of a payload with storage URLs."""

from collections.abc import Iterable
from typing import Any

from app.modules.admission.ports.media_mirror import MediaMirror


async def mirror_media(
    mirror: MediaMirror | None, values: dict[str, Any], fields: Iterable[str]
) -> dict[str, Any]:
    """Return `values` with every non-empty media field mirrored.

    Without a mirror the values are returned as they are.
    """
    if mirror is None:
        return values
    out = dict(values)
    for key in fields:
        url = out.get(key)
        if isinstance(url, str) and url:
            out[key] = await mirror.mirror(url)
    return out


def https_probe(url: str | None, mirror: MediaMirror | None) -> str | None:
    """`url` as https for validation when it is in our storage, else unchanged.

    Our storage is plain http in development; its URLs pass the https checks.
    """
    if url is None or mirror is None or not url.startswith(mirror.own_prefix):
        return url
    return "https://" + url.split("://", 1)[1]
