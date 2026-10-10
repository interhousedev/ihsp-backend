"""A user's dashboard layout and its default."""

from dataclasses import dataclass, field
from uuid import UUID, uuid5

from app.modules.dashboard.domain.errors import InvalidLayoutError
from app.modules.dashboard.domain.widget import LAYOUT_MARK, MAX_WIDGETS, Widget

_NAMESPACE = UUID("6f1d3c8e-2a4b-4c57-9d0e-5b7a1c2e9f40")


@dataclass(slots=True)
class Layout:
    """The widgets of one user; `version` grows by one on every save."""

    user_id: UUID
    version: int = 0
    widgets: list[Widget] = field(default_factory=list)


def validate_widgets(widgets: list[Widget]) -> None:
    """Raise InvalidLayoutError for too many widgets or repeated ids."""
    if len(widgets) > MAX_WIDGETS:
        raise InvalidLayoutError(params={"max": MAX_WIDGETS})
    if len({w.id for w in widgets}) != len(widgets):
        raise InvalidLayoutError(params={"max": MAX_WIDGETS})


def default_widgets(user_id: UUID) -> list[Widget]:
    """The layout of a user who never edited the dashboard."""
    rows: list[tuple[str, str, int, int]] = [
        ("next_lesson", "2x1", 0, 0),
        ("upcoming_controls", "2x1", 2, 0),
        ("today_lessons", "2x2", 0, 1),
        ("homework", "2x1", 2, 1),
        ("semester_summary", "1x1", 2, 2),
        ("new_marks", "1x1", 3, 2),
        ("announcements", "2x1", 0, 3),
        ("alerts", "2x1", 2, 3),
        ("get_started", "2x1", 0, 4),
        ("flashcards_due", "1x1", 2, 4),
        ("attendance", "1x1", 3, 4),
        ("notebook_prompt", "2x1", 0, 5),
    ]
    return [
        Widget.model_validate(
            {
                "id": uuid5(_NAMESPACE, f"{user_id}:{kind}"),
                "kind": kind,
                "size": size,
                "x": x,
                "y": y,
                "config": {LAYOUT_MARK[0]: LAYOUT_MARK[1]},
            }
        )
        for kind, size, x, y in rows
    ]
