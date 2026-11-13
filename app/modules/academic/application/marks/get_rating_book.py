"""The student's EMIS rating book (a PDF on the EMIS CDN)."""

from app.shared.actor import Actor
from app.shared.contracts.emis import EmisAuthFailed, EmisSource, EmisUnavailable


class GetRatingBook:
    """Asks EMIS to build the rating book and returns its link."""

    def __init__(self, *, emis: EmisSource) -> None:
        """Store collaborators."""
        self._emis = emis

    async def execute(self, actor: Actor) -> str:
        """Return the URL of the rating book PDF."""
        try:
            return await self._emis.rating_book(actor.user_id)
        except EmisAuthFailed as exc:  # a 401 here would log the student out
            raise EmisUnavailable(support_details="EMIS login needs a refresh") from exc
