"""In-memory fakes of the login cue port and of the group names."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.login_cue import LoginCue


class InMemoryLoginCueRepository:
    """Keeps cues in a dict; ``claim`` mirrors the conditional UPDATE."""

    def __init__(self) -> None:
        """Start empty."""
        self.cues: dict[UUID, LoginCue] = {}
        self.reserved: dict[UUID, datetime] = {}

    async def add(self, cues: Sequence[LoginCue]) -> None:
        """Insert all cues."""
        for cue in cues:
            self.cues[cue.id] = cue

    async def get(self, cue_id: UUID) -> LoginCue | None:
        """Return the cue or None."""
        return self.cues.get(cue_id)

    async def list_cues(self, group_id: UUID | None = None) -> list[LoginCue]:
        """Return the cues, newest first."""
        found = [c for c in self.cues.values() if group_id in (None, c.group_id)]
        return sorted(found, key=lambda c: c.created_at, reverse=True)

    async def delete(self, cue_id: UUID) -> bool:
        """Remove the cue if present."""
        return self.cues.pop(cue_id, None) is not None

    async def open_group_ids(self) -> list[UUID]:
        """Return the distinct groups of unconsumed cues."""
        return list({c.group_id for c in self.cues.values() if not c.consumed})

    async def open_for_group(self, group_id: UUID) -> list[LoginCue]:
        """Return unconsumed cues of a group, by name."""
        found = [
            c for c in self.cues.values() if c.group_id == group_id and not c.consumed
        ]
        return sorted(found, key=lambda c: c.full_name)

    async def reserve(
        self, cue_id: UUID, now: datetime, until: datetime
    ) -> LoginCue | None:
        """Hold an open cue unless another hold is still running."""
        cue = self.cues.get(cue_id)
        held = self.reserved.get(cue_id)
        if cue is None or cue.consumed or (held is not None and held > now):
            return None
        self.reserved[cue_id] = until
        return cue

    async def release(self, cue_id: UUID) -> None:
        """Drop the hold, if any."""
        self.reserved.pop(cue_id, None)

    async def claim(self, cue_id: UUID, now: datetime) -> bool:
        """Consume an unconsumed cue; False otherwise."""
        cue = self.cues.get(cue_id)
        if cue is None or cue.consumed:
            return False
        self.reserved.pop(cue_id, None)
        self.cues[cue_id] = LoginCue(
            id=cue.id,
            emis_login_enc=cue.emis_login_enc,
            login_tail=cue.login_tail,
            full_name=cue.full_name,
            group_id=cue.group_id,
            created_at=cue.created_at,
            consumed_at=now,
        )
        return True


class FakeCueGroups:
    """Group names of the AcademicEnrollment contract (only ``group_names`` is used)."""

    def __init__(self, names: dict[UUID, str] | None = None) -> None:
        """Start with the given active groups."""
        self.names: dict[UUID, str] = dict(names or {})

    async def group_names(self, group_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return the names of the known groups."""
        return {g: self.names[g] for g in group_ids if g in self.names}


class StubStart:
    """Stands in for StartRegistration: records the login it was given."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.logins: list[str] = []

    async def execute(
        self, *, emis_login: str, emis_password: str, ip: str | None, locale: str
    ) -> object:
        """Record the login; return a marker object."""
        self.logins.append(emis_login)
        return object()
