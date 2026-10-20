"""Attendance checklist: one toggle button per student plus the step actions."""

from collections.abc import Sequence
from uuid import UUID

from app.interfaces.bot.callbacks import WorkOffPromptCb
from app.interfaces.bot.prompt_state import RosterItem
from app.interfaces.bot.utilities.markup import (
    Button,
    Rows,
    cb_button,
    none_button,
    pairs,
)
from app.shared.contracts.callbacks import AttActionCb, AttToggleCb, HomeworkPromptCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

# Telegram allows 100 buttons per keyboard; keep room for headings and actions.
MAX_ROSTER_BUTTONS = 80
NAME_LIMIT = 22
ABSENT_MARK = "✗ "


def _sections(
    i18n: I18nContext, roster: Sequence[RosterItem]
) -> list[tuple[str | None, list[RosterItem]]]:
    """Group the roster: by group for merged lessons, unassigned students apart."""
    groups: dict[str, list[RosterItem]] = {}
    for item in roster:
        groups.setdefault(item.group_name, []).append(item)
    merged = len(groups) > 1
    sections: list[tuple[str | None, list[RosterItem]]] = []
    for group, items in groups.items():
        assigned = [item for item in items if not item.subgroup_unset]
        unassigned = [item for item in items if item.subgroup_unset]
        if assigned:
            sections.append((f"— {group} —" if merged else None, assigned))
        if unassigned:
            sections.append((i18n("bot-prompt-no-subgroup", group=group), unassigned))
    return sections


def _student_button(lesson: str, item: RosterItem) -> Button:
    name = item.name if len(item.name) <= NAME_LIMIT else item.name[:NAME_LIMIT] + "…"
    text = f"{ABSENT_MARK}{name}" if item.absent else name
    return cb_button(text, AttToggleCb(lesson=lesson, pos=item.position))


def roster_rows(
    i18n: I18nContext, lesson_id: UUID, roster: Sequence[RosterItem]
) -> Rows:
    """Return heading rows and toggle rows for the students that fit."""
    lesson = uuid_to_b64(lesson_id)
    rows: Rows = []
    shown = 0
    for heading, items in _sections(i18n, roster):
        items = items[: max(0, MAX_ROSTER_BUTTONS - shown)]
        if not items:
            break
        if heading is not None:
            rows.append([none_button(heading)])
        rows.extend(pairs([_student_button(lesson, item) for item in items]))
        shown += len(items)
    return rows


def get(i18n: I18nContext, lesson_id: UUID, roster: Sequence[RosterItem]) -> Rows:
    """Return the checklist: students, save buttons, work-off buttons, Set topic."""
    lesson = uuid_to_b64(lesson_id)
    rows = roster_rows(i18n, lesson_id, roster)
    rows.append(
        [
            cb_button(
                i18n("bot-btn-all-present"),
                AttActionCb(lesson=lesson, action="all_present"),
            ),
            cb_button(
                i18n("bot-btn-submit"), AttActionCb(lesson=lesson, action="submit")
            ),
        ]
    )
    rows.append(
        [
            cb_button(
                i18n("bot-btn-submit-no-work-off"),
                AttActionCb(lesson=lesson, action="submit_none"),
            )
        ]
    )
    rows.append(
        [
            cb_button(
                i18n("bot-btn-work-off-choose"),
                WorkOffPromptCb(lesson=lesson, action="menu"),
            ),
            cb_button(
                i18n("bot-btn-work-off-text"),
                WorkOffPromptCb(lesson=lesson, action="text"),
            ),
        ]
    )
    rows.append(
        [
            cb_button(
                i18n("bot-btn-topic"), HomeworkPromptCb(lesson=lesson, action="topic")
            )
        ]
    )
    return rows
