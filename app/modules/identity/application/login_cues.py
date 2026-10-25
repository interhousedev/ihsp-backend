"""Login cues: admin pre-registration of EMIS logins and the public picker (cues)."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.identity.application.register_ports import CredentialStore
from app.modules.identity.application.register_start import (
    StartedRegistration,
    StartRegistration,
)
from app.modules.identity.domain.login_cue import (
    LoginCue,
    login_tail,
    masked_login,
    short_names,
)
from app.modules.identity.ports.login_cue_repository import LoginCueRepository
from app.shared.base_error import NotFoundError, RateLimitedError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.emis import EmisAuthFailed
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

CUE_LIST_IP_LIMIT = 30
CUE_LIST_WINDOW_SECONDS = 600
# Wrong EMIS passwords per cue and hour; the cue then answers 429 until the window ends.
CUE_WRONG_PASSWORD_LIMIT = 5
CUE_WRONG_PASSWORD_WINDOW_SECONDS = 3600
# A registration holds its cue this long; a crash frees it when the hold runs out.
CUE_RESERVATION_SECONDS = 120


class LoginCueNotFoundError(NotFoundError):
    """The admin cue does not exist."""

    code = "id/login-cue-not-found"
    message_key = "id-login-cue-not-found"


class LoginCueGroupNotFoundError(NotFoundError):
    """A group in the request does not exist or is not active."""

    code = "id/login-cue-group-not-found"
    message_key = "id-login-cue-group-not-found"


class LoginCueUnavailableError(NotFoundError):
    """Unknown or already claimed cue; both look the same to students."""

    code = "id/login-cue-unavailable"
    message_key = "id-login-cue-unavailable"


@dataclass(frozen=True, slots=True)
class NewLoginCue:
    """One admin input row: the EMIS login is plain text until it is encrypted."""

    emis_login: str
    full_name: str
    group_id: UUID


@dataclass(frozen=True, slots=True)
class AdminLoginCue:
    """The admin view: the login is masked, never the full value."""

    id: UUID
    full_name: str
    group_id: UUID
    group_name: str
    login_masked: str
    created_at: datetime
    consumed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CueGroup:
    """A group that still has unclaimed cues."""

    group_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CueOption:
    """What a student sees: an opaque id and the name. Nothing else."""

    cue_id: UUID
    display_name: str


def _wrong_password_key(cue_id: UUID) -> str:
    return f"cue-wrong-password:{cue_id}"


class LoginCueService:
    """Admin CRUD of cues and the public registration picker over them."""

    def __init__(
        self,
        *,
        repository: LoginCueRepository,
        store: CredentialStore,
        groups: AcademicEnrollment,
        start: StartRegistration,
        rate_limiter: RateLimiter,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._repository = repository
        self._store = store
        self._groups = groups
        self._start = start
        self._rate_limiter = rate_limiter
        self._clock = clock

    # --- administrators -------------------------------------------------

    async def list_for_admin(self, group_id: UUID | None = None) -> list[AdminLoginCue]:
        """Return the cues, masked, with group names."""
        cues = await self._repository.list_cues(group_id)
        names = await self._groups.group_names(list({cue.group_id for cue in cues}))
        return [self._admin_view(cue, names.get(cue.group_id, "")) for cue in cues]

    async def create(self, items: list[NewLoginCue]) -> list[AdminLoginCue]:
        """Create cues in one transaction; all groups must exist."""
        cleaned = [self._clean(item) for item in items]
        names = await self._groups.group_names(list({c.group_id for c in cleaned}))
        if any(c.group_id not in names for c in cleaned):
            raise LoginCueGroupNotFoundError()
        now = self._clock.now()
        rows = []
        for item in cleaned:
            rows.append(
                LoginCue(
                    id=new_id(),
                    emis_login_enc=await self._store.encrypt(item.emis_login),
                    login_tail=login_tail(item.emis_login),
                    full_name=item.full_name,
                    group_id=item.group_id,
                    created_at=now,
                )
            )
        await self._repository.add(rows)
        return [self._admin_view(row, names[row.group_id]) for row in rows]

    async def delete(self, cue_id: UUID) -> None:
        """Delete a cue; unknown ids raise."""
        if not await self._repository.delete(cue_id):
            raise LoginCueNotFoundError()

    # --- public picker (no auth) ----------------------------------------

    async def groups_with_cues(self, ip: str | None) -> list[CueGroup]:
        """Return the groups that still have unclaimed cues, by name."""
        await self._limit(ip)
        ids = await self._repository.open_group_ids()
        names = await self._groups.group_names(ids)
        groups = [CueGroup(gid, names[gid]) for gid in ids if gid in names]
        return sorted(groups, key=lambda group: group.name)

    async def cues_of_group(self, group_id: UUID, ip: str | None) -> list[CueOption]:
        """Return the unclaimed cues of a group as opaque ids and given names."""
        await self._limit(ip)
        cues = await self._repository.open_for_group(group_id)
        names = short_names([cue.full_name for cue in cues])
        options = [CueOption(cue.id, name) for cue, name in zip(cues, names)]
        return sorted(options, key=lambda option: option.display_name)

    async def start_registration(
        self,
        *,
        cue_id: UUID,
        emis_password: str,
        ip: str | None,
        locale: str,
    ) -> StartedRegistration:
        """Start a registration with the login behind the cue.

        The cue is reserved first (one conditional UPDATE), so two concurrent requests
        cannot both start. A wrong EMIS password releases the reservation and counts
        toward the cue's limit; any other failure only releases it. The cue is claimed
        once EMIS accepted the password, so a typo does not use it up.
        """
        await self._rate_limiter.check(
            _wrong_password_key(cue_id), limit=CUE_WRONG_PASSWORD_LIMIT
        )
        now = self._clock.now()
        cue = await self._repository.reserve(
            cue_id, now, now + timedelta(seconds=CUE_RESERVATION_SECONDS)
        )
        if cue is None:
            raise LoginCueUnavailableError()
        try:
            login = await self._store.decrypt(cue.emis_login_enc)
            started = await self._start.execute(
                emis_login=login, emis_password=emis_password, ip=ip, locale=locale
            )
        except EmisAuthFailed:
            await self._repository.release(cue_id)
            await self._count_wrong_password(cue_id)
            raise
        except BaseException:
            await self._repository.release(cue_id)
            raise
        if not await self._repository.claim(cue_id, self._clock.now()):
            raise LoginCueUnavailableError()
        return started

    # --- helpers ---------------------------------------------------------

    async def _limit(self, ip: str | None) -> None:
        await self._rate_limiter.hit(
            f"login-cues:{ip or 'unknown'}",
            limit=CUE_LIST_IP_LIMIT,
            window_seconds=CUE_LIST_WINDOW_SECONDS,
        )

    async def _count_wrong_password(self, cue_id: UUID) -> None:
        # The limit is checked before each attempt; this only counts the failure.
        with suppress(RateLimitedError):
            await self._rate_limiter.hit(
                _wrong_password_key(cue_id),
                limit=CUE_WRONG_PASSWORD_LIMIT,
                window_seconds=CUE_WRONG_PASSWORD_WINDOW_SECONDS,
            )

    @staticmethod
    def _clean(item: NewLoginCue) -> NewLoginCue:
        login = item.emis_login.strip()
        name = " ".join(item.full_name.split())
        if not login or not name:
            raise ValidationFailedError(support_details="empty login or name")
        return NewLoginCue(emis_login=login, full_name=name, group_id=item.group_id)

    @staticmethod
    def _admin_view(cue: LoginCue, group_name: str) -> AdminLoginCue:
        return AdminLoginCue(
            id=cue.id,
            full_name=cue.full_name,
            group_id=cue.group_id,
            group_name=group_name,
            login_masked=masked_login(cue.login_tail),
            created_at=cue.created_at,
            consumed_at=cue.consumed_at,
        )
