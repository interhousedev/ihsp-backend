"""Serve only logo and cover URLs that live in our own storage.

The web apps' Content Security Policy allows images from our storage only, so an
external (for example Wikimedia) address would be blocked in the browser. Such
addresses are answered as null and the apps draw their monogram instead; the
`admission_mirror_media.py` job copies them into storage.
"""

from app.settings import Settings

_own_base: str | None = None


def configure_served_media(settings: Settings) -> None:
    """Remember `<public endpoint>/<bucket>/`; called once by the HTTP process."""
    global _own_base
    s3 = settings.s3
    _own_base = f"{s3.public_endpoint_url.rstrip('/')}/{s3.bucket}/"


def served_media(url: str | None) -> str | None:
    """Return `url` when it is in our storage, else None.

    Before `configure_served_media` runs (unit tests) every URL is kept.
    """
    if not url:
        return None
    if _own_base is None or url.startswith(_own_base):
        return url
    return None
