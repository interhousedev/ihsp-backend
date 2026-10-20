"""WO-1, WO-3, WO-4: work-off text, limits, modes and who gets notified."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.classwork.errors import (
    WorkOffNotAbsentError,
    WorkOffStatusInvalidError,
    WorkOffTemplateLimitError,
    WorkOffTemplateNotFoundError,
    WorkOffTextInvalidError,
    WorkOffTextRequiredError,
)
from app.modules.academic.domain.classwork.work_off import (
    ResolvedWorkOff,
    WorkOff,
    WorkOffChoice,
    WorkOffEntry,
    WorkOffTemplate,
    as_choice,
    as_entry,
    changed_students,
    clean_template_text,
    defaults_to_clear,
    ensure_status,
    ensure_template_capacity,
    notification_targets,
    plan_work_offs,
    resolve_text,
)

import pytest

NOW = dt.datetime(2026, 10, 6, 9, tzinfo=dt.UTC)


def template(is_default: bool = False) -> WorkOffTemplate:
    """A template of some teacher."""
    return WorkOffTemplate(uuid4(), uuid4(), "Redo", is_default, NOW, NOW)


def test_template_text_is_stripped_and_limited() -> None:
    """WO-1: 1..1000 characters after stripping."""
    assert clean_template_text("  Redo ex. 4 ") == "Redo ex. 4"
    for bad in ("   ", "x" * 1001):
        with pytest.raises(WorkOffTextInvalidError):
            clean_template_text(bad)


def test_twenty_templates_is_the_limit() -> None:
    """WO-1: a 21st template is refused."""
    ensure_template_capacity(19)

    with pytest.raises(WorkOffTemplateLimitError):
        ensure_template_capacity(20)


def test_only_one_default_survives() -> None:
    """WO-1: making a template the default clears the other defaults."""
    a, b, c = template(True), template(False), template(True)

    assert defaults_to_clear([a, b, c], b.id, True) == [a.id, c.id]
    assert defaults_to_clear([a, b, c], a.id, True) == [c.id]
    assert defaults_to_clear([a, b, c], b.id, False) == []


def test_text_is_template_then_blank_line_then_extra() -> None:
    """WO-3: the resolved text joins both parts with a blank line."""
    assert resolve_text("Redo", "p. 5") == "Redo\n\np. 5"
    assert resolve_text("Redo", None) == "Redo"
    assert resolve_text(None, " p. 5 ") == "p. 5"
    assert resolve_text(" ", "") is None


def test_resolved_text_over_2000_characters_is_refused() -> None:
    """WO-3: the stored limit is 2000."""
    with pytest.raises(WorkOffTextInvalidError):
        resolve_text("x" * 1000, "y" * 1000)


def test_status_must_be_known() -> None:
    """WO-3: only assigned and done exist."""
    assert ensure_status("done") == "done"
    with pytest.raises(WorkOffStatusInvalidError):
        ensure_status("late")


def test_per_student_plan_upserts_and_deletes() -> None:
    """WO-3: an entry with text is saved, an empty entry removes the task."""
    a, b, c = uuid4(), uuid4(), uuid4()
    tpl = uuid4()
    entries = [
        WorkOffEntry(a, WorkOffChoice(tpl, "p. 5")),
        WorkOffEntry(b, WorkOffChoice()),
    ]

    plan = plan_work_offs("per_student", {a, b, c}, entries, None, {tpl: "Redo"})

    assert plan.upserts == {a: ResolvedWorkOff("Redo\n\np. 5", tpl, None)}
    assert plan.deletes == {b}


def test_per_student_entry_for_a_present_student_is_refused() -> None:
    """WO-3: work-offs only go to absent students."""
    present = uuid4()

    with pytest.raises(WorkOffNotAbsentError):
        plan_work_offs(
            "per_student",
            set(),
            [WorkOffEntry(present, WorkOffChoice(text="x"))],
            None,
            {},
        )


def test_unknown_template_is_not_found() -> None:
    """WO-3: a template that is not the actor's counts as missing."""
    a = uuid4()

    with pytest.raises(WorkOffTemplateNotFoundError):
        plan_work_offs(
            "per_student",
            {a},
            [WorkOffEntry(a, WorkOffChoice(template_id=uuid4()))],
            None,
            {},
        )


def test_none_mode_plans_nothing() -> None:
    """WO-3: the "none" mode attaches nothing."""
    plan = plan_work_offs("none", {uuid4()}, [], None, {})

    assert not plan.upserts
    assert not plan.deletes


def test_common_mode_gives_every_absent_student_the_task() -> None:
    """WO-3: the common task overrides everyone."""
    a, b = uuid4(), uuid4()

    plan = plan_work_offs("common", {a, b}, [], WorkOffChoice(text="Read"), {})

    assert set(plan.upserts) == {a, b}
    assert plan.upserts[a].text == "Read"


def test_common_mode_without_text_is_refused() -> None:
    """WO-3: required and must resolve to text."""
    for common in (None, WorkOffChoice(text="  ")):
        with pytest.raises(WorkOffTextRequiredError):
            plan_work_offs("common", {uuid4()}, [], common, {})


def test_choice_and_entry_accept_json_like_mappings() -> None:
    """WO-3: the HTTP and bot layers may pass plain dicts."""
    student, tpl = uuid4(), uuid4()

    entry = as_entry(
        {"student_id": str(student), "template_id": str(tpl), "due_date": "2026-10-09"}
    )

    assert entry.student_id == student
    assert entry.choice == WorkOffChoice(tpl, None, dt.date(2026, 10, 9))
    assert as_choice(None) is None


def _work_off(student: UUID, text: str) -> WorkOff:
    return WorkOff(
        uuid4(), uuid4(), student, uuid4(), None, text, "assigned", None, None, NOW, NOW
    )


def test_changed_students_are_new_or_with_other_text() -> None:
    """WO-4: same text is not a change."""
    a, b, c = uuid4(), uuid4(), uuid4()
    existing = {a: _work_off(a, "same"), b: _work_off(b, "old")}
    upserts = {
        a: ResolvedWorkOff("same", None, None),
        b: ResolvedWorkOff("new", None, None),
        c: ResolvedWorkOff("fresh", None, None),
    }

    assert changed_students(existing, upserts) == {b, c}


def test_notification_targets_first_notice_and_update() -> None:
    """WO-4: newly absent get the first notice; changed work-offs get an update."""
    old, new, kept = uuid4(), uuid4(), uuid4()

    targets = notification_targets({old, kept}, {old, new, kept}, {old, new})

    assert targets == {new: False, old: True}
