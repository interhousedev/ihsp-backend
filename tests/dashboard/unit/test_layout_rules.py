"""Widget sizes, contrast text colour and the version check."""

from uuid import uuid4

from app.modules.dashboard.application.get_layout import GetLayout  # noqa: F401
from app.modules.dashboard.domain.errors import LayoutVersionConflictError
from app.modules.dashboard.domain.layout import keep_one_tile_per_kind
from app.modules.dashboard.domain.widget import (
    WIDGET_SIZES,
    Widget,
    contrast_ratio,
    text_on,
)
from app.modules.dashboard.wiring import DashboardServices

import pytest
from pydantic import ValidationError


def widget(kind: str = "timetable", size: str = "2x2", **extra: object) -> Widget:
    """A widget at the origin."""
    return Widget.model_validate(
        {"id": uuid4(), "kind": kind, "size": size, "x": 0, "y": 0, **extra}
    )


def test_size_must_be_allowed_for_kind() -> None:
    """A size outside WIDGET_SIZES[kind] is refused."""
    assert "1x1" not in WIDGET_SIZES["timetable"]
    with pytest.raises(ValidationError):
        widget("timetable", "1x1")


def test_every_allowed_size_is_accepted() -> None:
    """Each kind accepts all of its sizes."""
    for kind, sizes in WIDGET_SIZES.items():
        for size in sizes:
            assert widget(kind, size).size == size


def test_widget_must_fit_the_grid_width() -> None:
    """x + columns cannot pass the 4 columns."""
    with pytest.raises(ValidationError):
        Widget.model_validate(
            {"id": uuid4(), "kind": "timetable", "size": "2x2", "x": 3, "y": 0}
        )


def test_color_must_be_hex() -> None:
    """Only #rrggbb is stored."""
    with pytest.raises(ValidationError):
        widget(color="red")


def test_contrast_text_color() -> None:
    """Black text on light colours, white on dark."""
    assert text_on("#000000") == "#FFFFFF"
    assert text_on("#FFFFFF") == "#000000"


@pytest.mark.parametrize(
    "color",
    ["#FF3B30", "#FFCC00", "#34C759", "#007AFF", "#5856D6", "#777777", "#808080"],
)
def test_contrast_text_is_readable(color: str) -> None:
    """The picked text colour keeps a WCAG ratio of at least 4.5 on iOS-like tints."""
    assert contrast_ratio(color, text_on(color)) >= 4.5


async def test_get_returns_the_default_at_version_zero(
    dashboard: DashboardServices,
) -> None:
    """A user without a saved layout gets the default one."""
    layout = await dashboard.get_layout.execute(user_id=uuid4())

    assert layout.version == 0 and layout.widgets


async def test_save_bumps_the_version_and_stale_version_conflicts(
    dashboard: DashboardServices,
) -> None:
    """Saving with the stored version works once; the same version again conflicts."""
    user = uuid4()
    saved = await dashboard.save_layout.execute(
        user_id=user, version=0, widgets=[widget()]
    )
    assert saved.version == 1

    with pytest.raises(LayoutVersionConflictError):
        await dashboard.save_layout.execute(user_id=user, version=0, widgets=[])


TODAY_KINDS = {
    "upcoming_controls",
    "next_lesson",
    "today_lessons",
    "semester_summary",
    "announcements",
    "new_marks",
    "alerts",
    "get_started",
}


def test_today_sections_are_widget_kinds_with_sizes() -> None:
    """Every former fixed section of Today is a widget kind with allowed sizes."""
    assert TODAY_KINDS <= set(WIDGET_SIZES)
    assert all(WIDGET_SIZES[kind] for kind in TODAY_KINDS)
    assert "1x1" in WIDGET_SIZES["next_lesson"]
    assert "2x4" in WIDGET_SIZES["today_lessons"]
    with pytest.raises(ValidationError):
        widget("today_lessons", "1x1")


def test_default_layout_has_the_today_widgets_without_overlap() -> None:
    """The default layout holds the new kinds once each and no two tiles overlap."""
    from app.modules.dashboard.domain.layout import default_widgets
    from app.modules.dashboard.domain.widget import size_span

    widgets = default_widgets(uuid4())
    kinds = [w.kind for w in widgets]
    assert TODAY_KINDS <= set(kinds)
    assert len(kinds) == len(set(kinds))
    cells: set[tuple[int, int]] = set()
    for w in widgets:
        cols, rows = size_span(w.size)
        for dx in range(cols):
            for dy in range(rows):
                assert (w.x + dx, w.y + dy) not in cells
                cells.add((w.x + dx, w.y + dy))


def test_a_repeated_kind_keeps_its_first_tile() -> None:
    """The catalogue can add a kind already on the board; its first tile stays."""
    first = widget("flashcards_due", "1x1")

    kept = keep_one_tile_per_kind(
        [widget("next_lesson", "2x1"), first, widget("flashcards_due", "2x1")]
    )

    assert [w.kind for w in kept] == ["next_lesson", "flashcards_due"]
    assert kept[1].id == first.id


def test_notebook_prompts_may_repeat() -> None:
    """Each notebook prompt points at its own notebook, so they are not repeats."""
    prompts = [
        widget("notebook_prompt", "2x1", config={"notebook_id": str(uuid4())})
        for _ in range(2)
    ]

    assert keep_one_tile_per_kind(prompts) == prompts


async def test_save_stores_one_tile_per_kind(dashboard: DashboardServices) -> None:
    """A save with a repeated kind stores its first tile; reads give the same layout."""
    user = uuid4()
    first = widget("homework", "1x1")

    saved = await dashboard.save_layout.execute(
        user_id=user, version=0, widgets=[first, widget("homework", "2x1")]
    )
    fetched = await dashboard.get_layout.execute(user_id=user)

    assert [w.id for w in saved.widgets] == [first.id]
    assert fetched.version == 1
    assert [w.id for w in fetched.widgets] == [first.id]
