"""Log a user out everywhere: epoch, sessions, connectors, Hydra, Redis."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.domain.errors import HydraUnavailableError
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.revocation_list import AuthEpochCache, RevocationList
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RevokeResult:
    """What was revoked in the database; Redis and Hydra follow after commit."""

    user_id: UUID
    epoch: int
    session_ids: tuple[UUID, ...]
    connector_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class AccessRevoker:
    """Revokes all access of a user in the caller's transaction."""

    revocations: RevocationList
    epochs: AuthEpochCache
    hydra: HydraGateway
    clock: Clock

    async def revoke_in(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        *,
        keep_telegram: bool = False,
        except_session_id: UUID | None = None,
    ) -> RevokeResult:
        """Bump the epoch, revoke sessions and connectors; queue the after-commit work.

        The user is saved here. Redis revocations and Hydra calls run after the
        caller commits (uow.after_commit).
        """
        now = self.clock.now()
        user.bump_epoch()
        await uow.users.save(user)
        sessions = await uow.sessions.revoke_all(
            user.id, now, except_id=except_session_id
        )
        connectors = await uow.connectors.revoke_all_for_user(user.id, now)
        if not keep_telegram:
            await uow.telegram_links.delete_all_for_user(user.id)
        result = RevokeResult(
            user_id=user.id,
            epoch=user.auth_epoch,
            session_ids=tuple(s.id for s in sessions),
            connector_ids=tuple(c.id for c in connectors),
        )

        async def finish() -> None:
            await self._finish(result)

        uow.after_commit(finish)
        return result

    async def revoke_sessions_in(
        self,
        uow: IdentityUnitOfWorkPort,
        user_id: UUID,
        *,
        only_id: UUID | None = None,
        except_id: UUID | None = None,
    ) -> list[LoginSession]:
        """Revoke one session, or all of them except one; no epoch bump.

        The sessions' access tokens stop working through the revocation list, and
        the token hook refuses their refresh tokens.
        """
        now = self.clock.now()
        if only_id is not None:
            one = await uow.sessions.get(only_id)
            if one is None or one.user_id != user_id:
                return []
            revoked = await uow.sessions.revoke(only_id, now)
            sessions = [revoked] if revoked else []
        else:
            sessions = await uow.sessions.revoke_all(user_id, now, except_id=except_id)

        async def finish() -> None:
            await self._finish_sessions(sessions)

        uow.after_commit(finish)
        return sessions

    async def _finish_sessions(self, sessions: list[LoginSession]) -> None:
        for session in sessions:
            await self.revocations.revoke(session.id)
            if not session.hydra_sid:
                continue
            try:
                await self.hydra.revoke_login_sessions(sid=session.hydra_sid)
            except HydraUnavailableError:
                log.warning("hydra_revoke_failed", session_id=str(session.id))

    async def _finish(self, result: RevokeResult) -> None:
        await self.epochs.set(result.user_id, result.epoch)
        for identifier in (*result.session_ids, *result.connector_ids):
            await self.revocations.revoke(identifier)
        try:
            subject = str(result.user_id)
            await self.hydra.revoke_login_sessions(subject=subject)
            await self.hydra.revoke_consent_sessions(subject)
        except HydraUnavailableError:
            # Refresh is still blocked by the token hook (revoked sessions, new epoch).
            log.warning("hydra_revoke_failed", user_id=str(result.user_id))
