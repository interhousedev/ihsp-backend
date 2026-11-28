"""TeamPosition, TeamSeat, PositionApplication and form_schema (spec 4.3).

The implementation must provide `app.modules.activities.domain.team`:
  TeamPosition(id, club_id, title, description, slots, open_for_applications,
  form_schema, order)
  validate_answers(form_schema, answers) -> cleaned dict; raises FormAnswersInvalidError
    (params.field). form_schema = {"fields":[{"key","type":"text|choice|number|bool",
    "required":bool,"options":[...],"max_length":int}]}; unknown keys rejected.
  validate_form_schema(schema) raises FormSchemaInvalidError (dup keys, bad type, choice
  w/o options)
  PositionApplication.submit(position, user_id, answers, accepted_count) / .shortlist()
  /
    .accept(accepted_count, slots) / .reject(note) / .withdraw(); status
    submitted|shortlisted|accepted|rejected|withdrawn; ApplicationStateError,
    PositionFullError,
    PositionClosedError
  TeamSeat(position_id, user_id, since, until, public, consent_public, bio, experience).
    is_publicly_visible(now) -> public AND consent_public AND (until is None or until >
    now)
  TeamSeat.grant_consent(by_user, now) / .revoke_consent(by_user, now): ONLY the seat's
  own student may change
    `consent_public` (ConsentDeniedError for anyone else: club owner, SU, admin); each
    change records
    `consent_changed_at` and returns a ConsentEvent(seat user, granted, at) for the
    audit log; managers
    toggle only `public` (their publication flag) and never touch consent. Revoking
    takes effect at once
    (is_publicly_visible is False) and erasure/export cover both fields.
  public_name(first, last) -> 'Aziz K.' (first name + last initial only)
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.activities.domain.team import (
    ApplicationStateError,
    ConsentDeniedError,
    FormAnswersInvalidError,
    FormSchemaInvalidError,
    PositionApplication,
    PositionClosedError,
    PositionFullError,
    TeamPosition,
    TeamSeat,
    public_name,
    validate_answers,
    validate_form_schema,
)

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)
SCHEMA = {
    "fields": [
        {"key": "why", "type": "text", "required": True, "max_length": 20},
        {"key": "shift", "type": "choice", "required": True, "options": ["am", "pm"]},
        {"key": "hours", "type": "number", "required": False},
        {"key": "phone_ok", "type": "bool", "required": False},
    ]
}


def pos(**kw: object) -> TeamPosition:
    base: dict[str, object] = {
        "id": uuid4(),
        "club_id": uuid4(),
        "title": {"en": "PR"},
        "description": {"en": "d"},
        "slots": 1,
        "open_for_applications": True,
        "form_schema": SCHEMA,
        "order": 0,
    }
    base.update(kw)
    return TeamPosition(**base)  # type: ignore[arg-type]


def test_valid_answers_are_cleaned() -> None:
    out = validate_answers(SCHEMA, {"why": "I like it", "shift": "am", "hours": 3})
    assert out == {"why": "I like it", "shift": "am", "hours": 3}


@pytest.mark.parametrize(
    "answers",
    [
        {"shift": "am"},  # missing required
        {"why": "x", "shift": "night"},  # not an option
        {"why": "x" * 21, "shift": "am"},  # too long
        {"why": "x", "shift": "am", "hours": "many"},  # wrong type
        {"why": "x", "shift": "am", "evil": 1},  # unknown key
        {"why": "x", "shift": "am", "phone_ok": "yes"},  # wrong type
    ],
)
def test_invalid_answers_are_rejected(answers: dict) -> None:
    with pytest.raises(FormAnswersInvalidError):
        validate_answers(SCHEMA, answers)


def test_empty_schema_accepts_only_empty_answers() -> None:
    assert validate_answers({"fields": []}, {}) == {}
    with pytest.raises(FormAnswersInvalidError):
        validate_answers({"fields": []}, {"a": 1})


@pytest.mark.parametrize(
    "schema",
    [
        {"fields": [{"key": "a", "type": "text"}, {"key": "a", "type": "text"}]},
        {"fields": [{"key": "a", "type": "image"}]},
        {"fields": [{"key": "a", "type": "choice"}]},
        {"fields": [{"key": "", "type": "text"}]},
        {"nope": []},
    ],
)
def test_bad_schemas_are_rejected(schema: dict) -> None:
    with pytest.raises(FormSchemaInvalidError):
        validate_form_schema(schema)


def test_application_lifecycle() -> None:
    p = pos(slots=2)
    a = PositionApplication.submit(
        p, uuid4(), {"why": "ok", "shift": "pm"}, accepted_count=0
    )
    assert a.status == "submitted"
    a.shortlist()
    a.accept(accepted_count=1, slots=p.slots)
    assert a.status == "accepted"
    with pytest.raises(ApplicationStateError):
        a.withdraw()


def test_closed_position_refuses_applications() -> None:
    with pytest.raises(PositionClosedError):
        PositionApplication.submit(
            pos(open_for_applications=False), uuid4(), {"why": "o", "shift": "am"}, 0
        )


def test_application_answers_are_validated_on_submit() -> None:
    with pytest.raises(FormAnswersInvalidError):
        PositionApplication.submit(pos(), uuid4(), {}, accepted_count=0)


def test_accepting_beyond_slots_is_refused() -> None:
    a = PositionApplication.submit(
        pos(slots=1), uuid4(), {"why": "o", "shift": "am"}, 0
    )
    with pytest.raises(PositionFullError):
        a.accept(accepted_count=1, slots=1)
    assert a.status == "submitted"


def test_reject_keeps_the_note() -> None:
    a = PositionApplication.submit(pos(), uuid4(), {"why": "o", "shift": "am"}, 0)
    a.reject("not now")
    assert (a.status, a.note) == ("rejected", "not now")


def seat(**kw: object) -> TeamSeat:
    base: dict[str, object] = {
        "position_id": uuid4(),
        "user_id": uuid4(),
        "since": NOW,
        "until": None,
        "public": True,
        "consent_public": True,
        "bio": {"en": "b"},
        "experience": [],
    }
    base.update(kw)
    return TeamSeat(**base)  # type: ignore[arg-type]


def test_seat_is_public_only_with_flag_and_student_consent() -> None:
    assert seat().is_publicly_visible(NOW)
    assert not seat(public=False).is_publicly_visible(NOW)
    assert not seat(consent_public=False).is_publicly_visible(NOW)  # minors' opt-in


def test_only_the_student_grants_or_revokes_public_consent() -> None:
    sd = seat(consent_public=False)
    manager = uuid4()
    for bad in (manager, uuid4()):
        with pytest.raises(ConsentDeniedError):
            sd.grant_consent(bad, NOW)
    assert sd.consent_public is False
    ev = sd.grant_consent(sd.user_id, NOW)
    assert sd.consent_public and sd.consent_changed_at == NOW and ev.granted is True
    assert sd.is_publicly_visible(NOW)
    with pytest.raises(ConsentDeniedError):
        sd.revoke_consent(manager, NOW)
    ev2 = sd.revoke_consent(sd.user_id, NOW + timedelta(minutes=1))
    assert ev2.granted is False and not sd.is_publicly_visible(
        NOW + timedelta(minutes=1)
    )


def test_ended_seat_is_not_public() -> None:
    assert not seat(until=NOW - timedelta(days=1)).is_publicly_visible(NOW)


def test_public_name_is_first_name_and_last_initial() -> None:
    assert public_name("Aziz", "Karimov") == "Aziz K."
    assert public_name("Aziz", "") == "Aziz"
