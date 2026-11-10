"""Use case: approve or reject by the single-use button of Telegram."""

from uuid import UUID

from app.modules.academic.application.excuses.decide_excuse import DecideExcuse
from app.modules.academic.application.excuses.ports import DecisionTokens
from app.modules.academic.domain.excuses.errors import ExcuseNotFoundError
from app.modules.academic.domain.excuses.excuse import ExcuseStatus
from app.shared.actor import Actor, Role


class DecideExcuseByToken:
    """A token proves the button reached this user; access is re-checked."""

    def __init__(self, *, tokens: DecisionTokens, decide: DecideExcuse) -> None:
        """Store the token store and the decision use case."""
        self.tokens = tokens
        self.decide = decide

    async def execute(
        self, *, user_id: UUID, token: str, roles: frozenset[Role]
    ) -> ExcuseStatus:
        """Consume the token and decide.

        Raises:
            ExcuseNotFoundError: the token is unknown, used, expired or not the user's,
                or the user no longer curates the student.
            ExcuseNotPendingError: the request was decided another way.
        """
        grant = await self.tokens.consume(token, user_id)
        if grant is None:
            raise ExcuseNotFoundError()
        view = await self.decide.execute(
            actor=Actor(user_id=user_id, roles=roles),
            excuse_id=grant.excuse_id,
            approve=grant.approve,
        )
        return view.excuse.status
