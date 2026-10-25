"""Port: the daily token budget of the embedding jobs."""

from typing import Protocol


class TokenBudget(Protocol):
    """Tokens spent today by all embedding calls together."""

    async def remaining(self) -> int | None:
        """Tokens left for today; None when the budget has no limit."""
        ...

    async def spend(self, tokens: int) -> None:
        """Add the tokens a call was billed."""
        ...
