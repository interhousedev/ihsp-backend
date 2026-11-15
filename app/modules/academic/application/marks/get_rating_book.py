"""The student's EMIS rating book (a PDF on the EMIS CDN)."""

from app.shared.actor import Actor
from app.shared.contracts.emis import EmisSource


class GetRatingBook:
    """Asks EMIS to build the rating book and returns its link."""

    def __init__(self, *, emis: EmisSource) -> None:
        """Store collaborators."""
        self._emis = emis

    async def execute(self, actor: Actor) -> str:
        """Return the URL of the rating book PDF.

        ``EmisAuthFailed`` (409 ``emis/auth-failed``, the student must re-enter the
        EMIS password) and ``EmisUnavailable`` (an outage) reach the caller as they are.
        """
        return await self._emis.rating_book(actor.user_id)
