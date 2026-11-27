"""The caller's own group for every student: homeroom teacher, head student, members."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.group_standings import load_standings
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.group_standing import (
    Metric,
    Scope,
    StudentStanding,
    places,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import (
    IdentityDirectory,
    UserRef,
    UserStatus,
    peer_photo_ids,
)

PHOTO_URL_TTL_SECONDS = 600


def _full_name(user: UserRef) -> str:
    return f"{user.first_name} {user.last_name}".strip()


def _person(user: UserRef | None, photos: dict[UUID, str]) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": _full_name(user),
        "photo_url": photos.get(user.id),
    }


def _value(standing: StudentStanding, metric: Metric) -> float | None:
    return standing.gpa if metric == "gpa" else standing.attendance


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _top(
    metric: Metric,
    standings: dict[UUID, StudentStanding],
    users: dict[UUID, UserRef],
    photos: dict[UUID, str],
    me: UUID,
) -> list[dict[str, Any]]:
    """Classmates with a value, best first; equal values share a rank."""
    ranks = places((uid, _value(s, metric)) for uid, s in standings.items())
    ordered = sorted(
        ranks,
        key=lambda uid: (
            ranks[uid],
            users[uid].last_name.casefold(),
            users[uid].first_name.casefold(),
        ),
    )
    return [
        {
            "rank": ranks[uid],
            "student_id": uid,
            "full_name": _full_name(users[uid]),
            "photo_url": photos.get(uid),
            "value": _rounded(_value(standings[uid], metric)),
            "is_me": uid == me,
        }
        for uid in ordered
    ]


class GetMyGroup:
    """Return the caller's group (any student of it may read this).

    The homeroom teacher is the group's curator, with the public contacts that are
    shown to students. The head student is shown with name and photo, like the other
    members. Members are the active students of the group, sorted by name; blocked
    accounts are left out, and a blocked head student is null. Unassigned
    roles are null; a head student who has left the group is null too. Photo links
    live ten minutes and are not given for blocked or inactive accounts, nor for
    students who chose to hide their photo from classmates (except to themselves).

    The tops rank classmates by current-term GPA and attendance; `ranks` gives the
    group's place among the groups of its course and of the lyceum. Other groups
    appear only as aggregates (see `GetGroupRankings`).
    """

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return the group card, members, tops and group ranks for the caller."""
        standings = await load_standings(self._uow_factory, self._clock, actor)
        group = standings.group
        member_ids = list(group.student_ids)
        head_id = group.head_student_id if group.head_student_id in member_ids else None
        curator_id = group.curator_id
        wanted: set[UUID] = set(member_ids)
        if curator_id is not None:
            wanted.add(curator_id)
        users = await self._identity.get_users(sorted(wanted, key=str))
        member_ids = [
            uid
            for uid in member_ids
            if uid in users and users[uid].status is not UserStatus.BLOCKED
        ]
        if head_id not in member_ids:
            head_id = None

        visible = peer_photo_ids(actor.user_id, users)
        photos = await self._identity.photo_urls(
            visible, ttl_seconds=PHOTO_URL_TTL_SECONDS
        )

        members = sorted(
            (users[uid] for uid in member_ids),
            key=lambda u: (u.last_name.casefold(), u.first_name.casefold()),
        )
        homeroom: dict[str, Any] | None = None
        if curator_id is not None and curator_id in users:
            prefs = await self._identity.get_preferences(curator_id)
            homeroom = _person(users[curator_id], photos)
            if homeroom is not None:
                homeroom["contacts"] = prefs.contacts.model_dump(mode="json")

        visible_members = set(member_ids)
        classmates = {
            s.student_id: s
            for s in standings.students
            if s.group_id == group.id and s.student_id in visible_members
        }
        mine = standings.mine()
        head = _person(users[head_id], photos) if head_id is not None else None
        return {
            "id": group.id,
            "name": group.name,
            "size": len(member_ids),
            "is_head_student": head_id == actor.user_id,
            "homeroom_teacher": homeroom,
            "head_student": head,
            "members": [
                {
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "photo_url": photos.get(user.id),
                    "is_head_student": user.id == head_id,
                    "is_me": user.id == actor.user_id,
                }
                for user in members
            ],
            "group": {
                "id": group.id,
                "name": group.name,
                "course": mine.course if mine else group.course,
            },
            "curator": (
                None
                if homeroom is None
                else {
                    "id": homeroom["id"],
                    "full_name": homeroom["full_name"],
                    "photo_url": homeroom["photo_url"],
                }
            ),
            "members_count": len(member_ids),
            "top_by_grade": _top("gpa", classmates, users, photos, actor.user_id),
            "top_by_attendance": _top(
                "attendance", classmates, users, photos, actor.user_id
            ),
            "ranks": standings.ranks(),
        }


class GetGroupRankings:
    """All groups of the course or lyceum ranked by GPA or attendance.

    Only aggregates of other groups are returned, never their members.
    """

    def __init__(self, *, uow_factory: MarksUowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, actor: Actor, scope: Scope, metric: Metric
    ) -> list[dict[str, Any]]:
        """Return the ranked groups of the scope."""
        standings = await load_standings(self._uow_factory, self._clock, actor)
        return standings.rankings(scope, metric)
