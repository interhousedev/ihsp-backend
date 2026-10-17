"""Port: checks whether a URL answers."""

from typing import Protocol

from app.modules.lms.domain.authoring.link_check import LinkResult


class LinkChecker(Protocol):
    """Contacts a URL safely; never raises for an unreachable target."""

    async def check(self, url: str) -> LinkResult:
        """Return the status of the URL or the reason it failed."""
        ...
