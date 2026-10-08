"""Where Hydra's login, consent and logout URLs send the browser next."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.modules.identity.domain.errors import ChallengeUsedError


def page_url(id_url: str, page: str, param: str, challenge: str, **hints: str) -> str:
    """The static login app page that handles one Hydra challenge (``/login/``...).

    ``hints`` ride along in the query (for the login form: which client asks), so
    the page can draw its form at once instead of waiting for a request.
    """
    query = urlencode({param: challenge, **hints})
    return f"{id_url.rstrip('/')}{page}?{query}"


def used_target(error: ChallengeUsedError, fallback: str) -> str:
    """Hydra answers 410 with the URL to start over; without it use ``fallback``."""
    redirect = error.params.get("redirect_to")
    return redirect if isinstance(redirect, str) and redirect else fallback


def restart_login_url(request_url: str) -> str:
    """The original authorize request with ``prompt=login`` (a fresh login)."""
    parts = urlsplit(request_url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "prompt"]
    query.append(("prompt", "login"))
    return urlunsplit(parts._replace(query=urlencode(query)))
