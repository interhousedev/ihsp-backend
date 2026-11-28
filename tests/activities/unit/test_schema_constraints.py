"""Metadata-level guarantees that races cannot break (spec 4.14 exit tests cover the
real-DB races).

The ORM lives in `app.modules.activities.infrastructure.orm`; `Base.metadata` must
declare:
  * memberships: UNIQUE INDEX on (club_id) WHERE role = 'owner' AND status = 'active'
    (one active owner);
  * rsvps: UNIQUE (event_id, user_id);
  * points ledger: UNIQUE (source_type, source_id, user_id, reason) (award dedupe);
  * club_course_links: UNIQUE (club_id, course_id);
  * clubs: UNIQUE slug;  reminders/outbox use the notify dedupe key (no table here).
"""

from typing import Any

from app.modules.activities.infrastructure import orm

from sqlalchemy import Index, Table, UniqueConstraint


def _uniques(table: Table) -> list[tuple[frozenset[str], str | None]]:
    out = []
    for c in table.constraints:
        if isinstance(c, UniqueConstraint):
            out.append((frozenset(col.name for col in c.columns), None))
    for i in table.indexes:
        if isinstance(i, Index) and i.unique:
            where = i.dialect_options["postgresql"].get("where")
            out.append(
                (
                    frozenset(col.name for col in i.columns),
                    str(where) if where is not None else None,
                )
            )
    return out


def _table(name: str) -> Any:
    return orm.Base.metadata.tables[name]


def test_one_active_owner_per_club_is_a_partial_unique_index() -> None:
    hits = [
        w
        for cols, w in _uniques(_table("activities_memberships"))
        if cols == {"club_id"}
    ]
    assert hits and "owner" in hits[0] and "active" in hits[0]


def test_rsvp_is_unique_per_event_and_user() -> None:
    assert (frozenset({"event_id", "user_id"}), None) in _uniques(
        _table("activities_rsvps")
    )


def test_points_award_dedupe_key_is_unique() -> None:
    assert (
        frozenset({"source_type", "source_id", "user_id", "reason"}),
        None,
    ) in _uniques(_table("activities_points_ledger"))


def test_course_link_pair_and_club_slug_are_unique() -> None:
    assert (frozenset({"club_id", "course_id"}), None) in _uniques(
        _table("activities_club_courses")
    )
    assert any(cols == {"slug"} for cols, _ in _uniques(_table("activities_clubs")))
