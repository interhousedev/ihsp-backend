"""FilesViews over fake `ListMyFiles` and `FilesApi`."""

import datetime as dt
from typing import Any

from app.bootstrap.adapters.composition.files_views import FilesViewsAdapter
from app.interfaces.http.v1.files.schemas import FileItem
from app.modules.files.application.list_my_files import FilePage
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.bootstrap.composition.data import make_view
from tests.bootstrap.composition.fakes import FakeFilesApi, FakeUseCase

OWNER = new_id()


def adapter(
    *pages: FilePage, hits: list[dict[str, Any]] | None = None
) -> tuple[FilesViewsAdapter, FakeUseCase, FakeFilesApi]:
    """The adapter over fake pages and fake text hits."""
    listing, api = FakeUseCase(*pages), FakeFilesApi(hits)
    return FilesViewsAdapter(listing, api), listing, api  # type: ignore[arg-type]


async def test_expiry_dates_are_sorted_and_cut_at_the_horizon() -> None:
    """Only ready files with a date on or before `until`, ascending."""
    views = [
        make_view("c.pdf", expires_on=dt.date(2026, 10, 20)),
        make_view("a.pdf", expires_on=dt.date(2026, 10, 12)),
        make_view("never.pdf", expires_on=None),
        make_view("b.pdf", expires_on=dt.date(2026, 10, 10)),
        make_view(
            "rejected.pdf", status=FileStatus.REJECTED, expires_on=dt.date(2026, 10, 1)
        ),
    ]
    files, listing, _ = adapter(FilePage(items=views, next_cursor=None))

    dates = await files.expiry_dates(OWNER, dt.date(2026, 10, 15))

    assert dates == [dt.date(2026, 10, 10), dt.date(2026, 10, 12)]
    (actor, *_), kwargs = listing.calls[0]
    assert actor.user_id == OWNER
    assert Role.STUDENT in actor.roles
    assert kwargs["limit"] == 100


async def test_expiry_dates_read_every_page() -> None:
    """The adapter follows the cursor until the last page."""
    first = FilePage(
        items=[make_view("a.pdf", expires_on=dt.date(2026, 10, 9))], next_cursor="c2"
    )
    second = FilePage(
        items=[make_view("b.pdf", expires_on=dt.date(2026, 10, 8))], next_cursor=None
    )
    files, listing, _ = adapter(first, second)

    dates = await files.expiry_dates(OWNER, dt.date(2026, 12, 31))

    assert dates == [dt.date(2026, 10, 8), dt.date(2026, 10, 9)]
    assert [call[1]["cursor"] for call in listing.calls] == [None, "c2"]


async def test_search_returns_file_items_text_hits_first_then_names() -> None:
    """Text matches lead, name matches follow, duplicates collapse, limit applies."""
    by_text = make_view("lecture-3.pdf")
    by_name = make_view("Calculus summary.pdf")
    both = make_view("calculus-text.pdf")
    other = make_view("physics.pdf")
    hits = [
        {"file_id": by_text.file.id, "name": by_text.file.name, "snippet": "..."},
        {"file_id": both.file.id, "name": both.file.name, "snippet": "..."},
    ]
    files, _, api = adapter(
        FilePage(items=[other, by_name, both, by_text], next_cursor=None), hits=hits
    )

    found = await files.search_files(OWNER, "Calculus", 5)

    assert [item["name"] for item in found] == [
        "lecture-3.pdf",
        "calculus-text.pdf",
        "Calculus summary.pdf",
    ]
    assert api.calls == [(OWNER, "Calculus", 5)]
    for item in found:
        assert FileItem.model_validate(item).status == FileStatus.READY
    assert found[0]["id"] == str(by_text.file.id)
    assert found[0]["byte_size"] == 1234


async def test_search_respects_the_limit_and_skips_unready_files() -> None:
    """A rejected file never shows up, even when its name matches."""
    views = [make_view(f"notes-{n}.pdf") for n in range(4)]
    views.append(make_view("notes-bad.pdf", status=FileStatus.REJECTED))
    files, _, _ = adapter(FilePage(items=views, next_cursor=None))

    found = await files.search_files(OWNER, "notes", 3)

    assert len(found) == 3
    assert all(item["status"] == "ready" for item in found)


async def test_search_ignores_text_hits_of_unknown_files() -> None:
    """A hit whose file is not in the owner's list is dropped."""
    files, _, _ = adapter(
        FilePage(items=[], next_cursor=None),
        hits=[{"file_id": new_id(), "name": "ghost.pdf", "snippet": ""}],
    )

    assert await files.search_files(OWNER, "ghost", 5) == []
