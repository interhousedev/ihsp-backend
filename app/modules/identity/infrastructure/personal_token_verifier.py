"""Verifies ihsp_pat_ personal tokens against the database."""

from datetime import timedelta

from app.modules.identity.domain.personal_token import looks_like_token
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import UnauthorizedError
from app.shared.clock import Clock
from app.shared.ids import hash_token

TOUCH_INTERVAL = timedelta(minutes=1)


def _unauthorized(reason: str) -> UnauthorizedError:
    return UnauthorizedError(support_details=f"personal token: {reason}")


class DbPersonalTokenVerifier:
    """PersonalTokenVerifier: active token, active user."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Keep the unit of work factory and the clock."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def verify_personal(self, token: str) -> Actor:
        """Return the actor carrying the token's scopes, or raise UnauthorizedError."""
        if not looks_like_token(token):
            raise _unauthorized("format")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            stored = await uow.personal_tokens.get_by_hash(hash_token(token))
            if stored is None or not stored.is_active(now):
                raise _unauthorized("unknown, revoked or expired")
            user = await uow.users.get(stored.user_id)
            if user is None or not user.is_active:
                raise _unauthorized("user inactive")
            await uow.personal_tokens.touch_last_used(
                stored.id, now, min_interval=TOUCH_INTERVAL
            )
            await uow.commit()
            return Actor(
                user_id=user.id,
                roles=frozenset(user.roles),
                scopes=frozenset(stored.scopes),
            )
