"""The answer of Hydra's login, consent and logout URLs: a plain redirect."""

from fastapi.responses import RedirectResponse


def hydra_redirect(url: str) -> RedirectResponse:
    """302 to ``url``; never cached, because the challenge is single use."""
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
