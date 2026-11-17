"""The admission assistant's data as the AI module sees it.

The admission assistant is an ordinary chat of the AI module (assistant
`admission`); its tools read the applicant's own application, search the FAQ
and suggest courses, opportunities, scholarships and universities through this
port. Admission checks the applicant, ownership and the AI consent on every call.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.shared.actor import Actor

SuggestionKind = Literal["course", "opportunity", "scholarship", "university"]
SUGGESTION_KINDS: tuple[SuggestionKind, ...] = (
    "course",
    "opportunity",
    "scholarship",
    "university",
)


@dataclass(frozen=True, slots=True)
class SuggestionCard:
    """One suggestion the student can add with one click."""

    type: SuggestionKind
    id: str
    title: str
    reason: str
    link: str


@dataclass(frozen=True, slots=True)
class FaqHit:
    """A published FAQ article that matches a search."""

    id: str
    title: str
    snippet: str
    locale: str
    link: str
    tags: list[str] = field(default_factory=list)


class AdmissionAssistantApi(Protocol):
    """What the admission assistant may read and add for its applicant."""

    async def require_assistant(self, actor: Actor) -> None:
        """Raise unless the actor may use the admission assistant."""
        ...

    async def admit_turn(self, actor: Actor) -> None:
        """Check the AI consent and count a turn against the daily soft limit."""
        ...

    async def application(self, actor: Actor) -> dict[str, Any]:
        """The applicant's whole application as plain JSON."""
        ...

    async def search_faq(
        self, actor: Actor, query: str, locale: str, limit: int
    ) -> list[FaqHit]:
        """Published FAQ articles for a query, the locale's first."""
        ...

    async def suggest(
        self, actor: Actor, kind: SuggestionKind, query: str, limit: int
    ) -> list[SuggestionCard]:
        """Suggestions of one kind the applicant has not added yet."""
        ...

    async def describe(
        self, actor: Actor, kind: SuggestionKind, item_id: str
    ) -> SuggestionCard:
        """The card of one suggestion (for an approval preview)."""
        ...

    async def add_suggestion(
        self, actor: Actor, kind: SuggestionKind, item_id: str
    ) -> SuggestionCard:
        """Add the suggestion to the applicant's plan, list or courses."""
        ...
