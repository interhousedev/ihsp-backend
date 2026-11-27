"""Team positions, applications, seats with the student's own public consent."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.domain.errors import Conflict, Denied, Invalid

__all__ = [
    "ApplicationStateError",
    "ConsentDeniedError",
    "ConsentEvent",
    "FormAnswersInvalidError",
    "FormSchemaInvalidError",
    "PositionApplication",
    "PositionClosedError",
    "PositionFullError",
    "TeamPosition",
    "TeamSeat",
    "public_name",
    "validate_answers",
    "validate_form_schema",
]

FIELD_TYPES = ("text", "choice", "number", "bool")
DEFAULT_MAX_LENGTH = 2000


class FormSchemaInvalidError(Invalid):
    """The form definition is malformed."""


class FormAnswersInvalidError(Invalid):
    """The answers do not fit the form. Params: field."""


class ApplicationStateError(Conflict):
    """The application is not in a state that allows this."""


class PositionFullError(Conflict):
    """Every slot of the position is taken."""


class PositionClosedError(Conflict):
    """The position takes no applications."""


class ConsentDeniedError(Denied):
    """Only the seat's own student changes the public consent."""


def validate_form_schema(schema: dict[str, Any]) -> None:
    """Raise `FormSchemaInvalidError` for a malformed form."""
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        raise FormSchemaInvalidError(params={"field": "fields"})
    seen: set[str] = set()
    for f in fields:
        key = f.get("key") if isinstance(f, dict) else None
        if not isinstance(key, str) or not key or key in seen:
            raise FormSchemaInvalidError(params={"field": "key"})
        seen.add(key)
        if f.get("type") not in FIELD_TYPES:
            raise FormSchemaInvalidError(params={"field": key})
        if f["type"] == "choice" and not f.get("options"):
            raise FormSchemaInvalidError(params={"field": key})


def _bad(key: str) -> FormAnswersInvalidError:
    return FormAnswersInvalidError(params={"field": key})


def _check(f: dict[str, Any], value: Any) -> None:
    key, kind = f["key"], f["type"]
    if kind == "text":
        if not isinstance(value, str) or len(value) > f.get(
            "max_length", DEFAULT_MAX_LENGTH
        ):
            raise _bad(key)
    elif kind == "choice":
        if value not in f["options"]:
            raise _bad(key)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise _bad(key)
    elif not isinstance(value, bool):
        raise _bad(key)


def validate_answers(schema: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Return the cleaned answers or raise `FormAnswersInvalidError`."""
    fields = {f["key"]: f for f in schema.get("fields", [])}
    for key in answers:
        if key not in fields:
            raise _bad(key)
    for key, f in fields.items():
        if key not in answers:
            if f.get("required"):
                raise _bad(key)
            continue
        _check(f, answers[key])
    return dict(answers)


@dataclass(slots=True)
class TeamPosition:
    """A seat the club recruits for."""

    id: UUID
    club_id: UUID
    title: Any
    description: Any
    slots: int
    open_for_applications: bool
    form_schema: dict[str, Any]
    order: int = 0


@dataclass(slots=True)
class PositionApplication:
    """A student's application to a position."""

    position_id: UUID
    user_id: UUID
    answers: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    status: str = "submitted"
    note: str | None = None

    @classmethod
    def submit(
        cls,
        position: TeamPosition,
        user_id: UUID,
        answers: dict[str, Any],
        accepted_count: int,
    ) -> "PositionApplication":
        """Apply to an open position with valid answers."""
        if not position.open_for_applications:
            raise PositionClosedError()
        if accepted_count >= position.slots:
            raise PositionFullError()
        clean = validate_answers(position.form_schema, answers)
        return cls(position.id, user_id, clean)

    def _from(self, allowed: tuple[str, ...]) -> None:
        if self.status not in allowed:
            raise ApplicationStateError(params={"status": self.status})

    def shortlist(self) -> None:
        """Move to the short list."""
        self._from(("submitted",))
        self.status = "shortlisted"

    def accept(self, accepted_count: int, slots: int) -> None:
        """Accept while a slot is free."""
        self._from(("submitted", "shortlisted"))
        if accepted_count >= slots:
            raise PositionFullError()
        self.status = "accepted"

    def reject(self, note: str | None) -> None:
        """Reject with a note."""
        self._from(("submitted", "shortlisted"))
        self.status = "rejected"
        self.note = note

    def withdraw(self) -> None:
        """The student withdraws."""
        self._from(("submitted", "shortlisted"))
        self.status = "withdrawn"


@dataclass(frozen=True, slots=True)
class ConsentEvent:
    """An audit fact: the student granted or revoked public display."""

    user_id: UUID
    granted: bool
    at: datetime


@dataclass(slots=True)
class TeamSeat:
    """A team person. Public only with the manager flag AND the student's consent."""

    position_id: UUID
    user_id: UUID
    since: datetime
    until: datetime | None
    public: bool
    consent_public: bool
    bio: Any
    experience: list[Any]
    photo_url: str | None = None
    consent_changed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)

    def is_publicly_visible(self, now: datetime) -> bool:
        """Published, consented and not ended."""
        return (
            self.public
            and self.consent_public
            and (self.until is None or self.until > now)
        )

    def _set_consent(self, by_user: UUID, now: datetime, granted: bool) -> ConsentEvent:
        if by_user != self.user_id:
            raise ConsentDeniedError()
        self.consent_public = granted
        self.consent_changed_at = now
        return ConsentEvent(self.user_id, granted, now)

    def grant_consent(self, by_user: UUID, now: datetime) -> ConsentEvent:
        """The student agrees to be shown."""
        return self._set_consent(by_user, now, True)

    def revoke_consent(self, by_user: UUID, now: datetime) -> ConsentEvent:
        """The student withdraws; effective at once."""
        return self._set_consent(by_user, now, False)


def public_name(first: str, last: str) -> str:
    """First name and the last initial."""
    return f"{first} {last[0]}." if last else first
