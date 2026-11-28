"""GET /v1/me/group standings and /v1/me/group/rankings on the real database."""

from uuid import UUID

from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Actor, Role
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.world import add_student

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _student(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


async def test_my_group_has_tops_and_ranks_without_other_groups_members(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """The card lists classmates only; rankings carry aggregates only."""
    w = env.world
    other = await add_student(sessionmaker_in_tx, w)
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    env.identity.add(make_user(other, first_name="Bek", last_name="Sadikov"))

    data = await services.get_my_group.execute(_student(w.user_id))

    assert data["group"]["id"] == w.group_id
    assert data["members_count"] == 2
    ids = {row["student_id"] for row in data["top_by_grade"]}
    ids |= {row["student_id"] for row in data["top_by_attendance"]}
    assert ids <= {w.user_id, other}
    assert set(data["ranks"]) == {"course", "lyceum"}
    for scope in ("course", "lyceum"):
        assert set(data["ranks"][scope]) == {"gpa", "attendance"}

    items = await services.get_group_rankings.execute(
        _student(w.user_id), "lyceum", "gpa"
    )
    for item in items:
        assert set(item) == {
            "place",
            "group_id",
            "group_name",
            "course",
            "value",
            "members_count",
            "is_mine",
        }
    places = [item["place"] for item in items]
    assert places == sorted(places)
