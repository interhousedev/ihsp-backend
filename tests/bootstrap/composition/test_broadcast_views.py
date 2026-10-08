"""BroadcastViews over a fake `ListBroadcasts`: scheduled ones, soonest first."""

import datetime as dt

from app.bootstrap.adapters.composition.broadcast_views import BroadcastViewsAdapter
from app.interfaces.http.v1.composition.admin_schemas import BroadcastItemResponse
from app.modules.admin.application.broadcast_view import BroadcastPageView
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.shared.actor import Role
from tests.bootstrap.composition.data import make_broadcast_view
from tests.bootstrap.composition.fakes import FakeUseCase
from tests.factories import make_actor

SOON = dt.datetime(2026, 10, 7, 4, 0, tzinfo=dt.UTC)


async def test_scheduled_returns_the_soonest_first_and_cuts_at_the_limit() -> None:
    """The use case lists newest-created first; the adapter sorts by send time."""
    late = make_broadcast_view("Late", scheduled_at=SOON + dt.timedelta(days=5))
    soon = make_broadcast_view("Soon", scheduled_at=SOON)
    middle = make_broadcast_view("Middle", scheduled_at=SOON + dt.timedelta(days=1))
    pages = [
        BroadcastPageView(items=[late, soon], next_cursor="more"),
        BroadcastPageView(items=[middle], next_cursor=None),
    ]
    listing = FakeUseCase(*pages)
    views = BroadcastViewsAdapter(listing)  # type: ignore[arg-type]
    actor = make_actor(Role.ADMIN)

    items = await views.scheduled(actor, 2)

    assert [item["title"] for item in items] == ["Soon", "Middle"]
    first_call, second_call = listing.calls
    assert first_call[0] == (actor,)
    assert first_call[1] == {
        "status": BroadcastStatus.SCHEDULED,
        "cursor": None,
        "limit": 100,
    }
    assert second_call[1]["cursor"] == "more"


async def test_scheduled_items_are_broadcast_items() -> None:
    """Every field of `BroadcastItem` is there, as JSON."""
    view = make_broadcast_view("Exam week", scheduled_at=SOON)
    page = BroadcastPageView(items=[view], next_cursor=None)
    views = BroadcastViewsAdapter(FakeUseCase(page))  # type: ignore[arg-type]

    (item,) = await views.scheduled(make_actor(Role.ADMIN), 5)

    assert item["id"] == str(view.broadcast.id)
    assert item["status"] == "scheduled"
    assert item["scheduled_at"] == "2026-10-07T04:00:00Z"
    assert item["audience"] == {
        "everyone": True,
        "roles": [],
        "group_ids": [],
        "semesters": [],
    }
    assert item["author"]["last_name"] == "Karimova"
    assert item["stats"] == {"total": 0, "sent": 0, "failed": 0, "blocked": 0}
    parsed = BroadcastItemResponse.model_validate(item)
    assert parsed.title == "Exam week"
    assert parsed.created_via == "ui"


async def test_scheduled_is_empty_without_broadcasts() -> None:
    """Nothing scheduled: an empty list."""
    page = BroadcastPageView(items=[], next_cursor=None)
    views = BroadcastViewsAdapter(FakeUseCase(page))  # type: ignore[arg-type]

    assert await views.scheduled(make_actor(Role.ADMIN), 5) == []
