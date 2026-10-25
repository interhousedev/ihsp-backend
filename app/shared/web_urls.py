"""One spelling per web page: the normalised URL of stored pages and known sources.

The rules are those of the notebooks' URL sources (`normalise_url` in
`notebooks.application.readers.url_reader`): lower-case scheme and host, no fragment, no
default port, a path of at least `/`, the query kept as it is. A notebook's URL source
has the key `url:<normalised>`, so a search can compare its pages with the sources
already in a notebook without importing the notebooks module.
"""

from urllib.parse import urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_web_url(raw: str) -> str | None:
    """The normalised form of an http(s) URL with a host; None for anything else."""
    try:
        parts = urlsplit(raw.strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not host or "@" in parts.netloc:
        return None
    name = f"[{host}]" if ":" in host else host
    netloc = name if port in (None, DEFAULT_PORTS[scheme]) else f"{name}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
