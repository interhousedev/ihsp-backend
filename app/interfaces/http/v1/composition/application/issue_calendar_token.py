"""Use case: create or rotate the secret iCal feed URL (WEB-6, UF-WEB-04)."""

from app.interfaces.http.v1.composition.errors import StudentNotFoundError
from app.interfaces.http.v1.composition.ports import CalendarTokenStore
from app.shared.actor import Actor
from app.shared.ids import hash_token, random_token


class IssueCalendarToken:
    """Gives the student a fresh feed URL and disables the previous one."""

    def __init__(self, *, tokens: CalendarTokenStore, api_url: str) -> None:
        """Store the token store and the public API origin (`URLS__API`)."""
        self.tokens = tokens
        self.api_url = api_url.rstrip("/")

    async def execute(self, actor: Actor) -> str:
        """Return the feed URL; this is the only time the token is visible."""
        token = random_token()
        if not await self.tokens.rotate(actor.user_id, hash_token(token)):
            raise StudentNotFoundError(support_details=str(actor.user_id))
        return f"{self.api_url}/ical/{token}.ics"
