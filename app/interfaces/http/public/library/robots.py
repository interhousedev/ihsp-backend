"""robots.txt of the library host and the check that tells the host apart."""

from urllib.parse import urlparse

from app.settings import LibrarySettings

from fastapi import Request

DISALLOWED = ("/manage/", "/my/", "/upload/", "/read/", "/lists/", "/v1/")


def library_robots_txt(settings: LibrarySettings) -> str:
    """Public pages and the sitemap may be crawled; the app's own pages not."""
    base = settings.public_base_url.rstrip("/")
    lines = ["User-agent: *", "Allow: /b/", "Allow: /sitemap.xml"]
    lines += [f"Disallow: {path}" for path in DISALLOWED]
    lines.append(f"Sitemap: {base}/sitemap.xml")
    return "\n".join(lines) + "\n"


def request_host(request: Request) -> str:
    """The host the client asked for (the proxy's `X-Forwarded-Host` wins)."""
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    host = forwarded or request.headers.get("host", "")
    return host.split(":")[0].lower()


def is_library_host(request: Request, settings: LibrarySettings) -> bool:
    """True when the request is for `library.ihsu.uz` (the configured public host)."""
    expected = (urlparse(settings.public_base_url).hostname or "").lower()
    return bool(expected) and request_host(request) == expected
