"""Widget sizes, contrast text colour and the version check."""

from uuid import uuid4

from app.modules.dashboard.application.get_layout import GetLayout  # noqa: F401
from app.modules.dashboard.domain.errors import LayoutVersionConflictError
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
