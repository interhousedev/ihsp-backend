"""Tasks domain: statuses, overdue, steps, deadline and link validation."""

import datetime as dt

from app.modules.admission.domain.errors import CharLimitError, InvalidAnswerError
from app.modules.admission.domain.tasks import (
    STEPS_MAX,
    Task,
    TaskLink,
    TaskStep,
    check_deadline,
    clean_links,
    clean_steps,
)
from app.shared.ids import new_id

import pytest

NOW = dt.datetime(2026, 3, 10, 9, 0, tzinfo=dt.UTC)
TODAY = NOW.date()


def _task(**kw: object) -> Task:
    base: dict[str, object] = {"title": "Draft essay", **kw}
    return Task(id=new_id(), student_id=new_id(), **base)  # type: ignore[arg-type]


def test_defaults_and_progress() -> None:
    t = _task(steps=(TaskStep(new_id(), "a"), TaskStep(new_id(), "b", done=True)))
    assert (t.status, t.priority, t.created_by) == ("planned", "medium", "student")
    assert t.progress == (1, 2)


def test_overdue_only_when_open_and_past_deadline() -> None:
    t = _task(deadline=TODAY - dt.timedelta(days=1))
    assert t.is_overdue(TODAY)
    t.set_status("done", NOW)
    assert not t.is_overdue(TODAY)
    assert not _task(deadline=TODAY).is_overdue(TODAY)
    assert not _task().is_overdue(TODAY)


def test_status_done_sets_and_reopen_clears_completion() -> None:
    t = _task()
    t.set_status("in_progress", NOW)
    assert t.completed_at is None
    t.set_status("done", NOW)
    assert t.completed_at == NOW
    t.set_status("blocked", NOW)
    assert t.completed_at is None


def test_unknown_status_is_refused() -> None:
    with pytest.raises(InvalidAnswerError):
        _task().set_status("archived", NOW)


def test_completing_all_steps_does_not_close_the_task() -> None:
    step = TaskStep(new_id(), "only")
    t = _task(steps=(step,))
    t.toggle_step(step.id, True)
    assert t.progress == (1, 1)
    assert t.status == "planned"
    t.toggle_step(step.id, False)
    assert t.progress == (0, 1)


def test_toggle_unknown_step_is_refused() -> None:
    with pytest.raises(InvalidAnswerError):
        _task().toggle_step(new_id(), True)


def test_deadline_before_2000_is_refused() -> None:
    with pytest.raises(InvalidAnswerError):
        check_deadline(dt.date(1901, 1, 1), None)
    assert check_deadline(dt.date(2000, 1, 1), None) == dt.date(2000, 1, 1)
    assert check_deadline(None, None) is None


def test_deadline_before_start_is_refused() -> None:
    with pytest.raises(InvalidAnswerError):
        check_deadline(dt.date(2026, 3, 1), dt.date(2026, 3, 5))


def test_validate_title_and_priority() -> None:
    t = _task()
    t.title = " "
    with pytest.raises(CharLimitError):
        t.validate()
    t.title = "ok"
    t.priority = "urgent"
    with pytest.raises(InvalidAnswerError):
        t.validate()


def test_links_kind_rules() -> None:
    ok = clean_links(
        [
            TaskLink("Site", "https://example.com/a", "external"),
            TaskLink("Essay", "/essays/edit?id=1", "internal"),
        ]
    )
    assert [x.kind for x in ok] == ["external", "internal"]
    for bad in (
        TaskLink("x", "javascript:alert(1)", "external"),
        TaskLink("x", "https://evil.test", "internal"),
        TaskLink("x", "//evil.test/a", "internal"),
        TaskLink("x", "/a", "other"),
    ):
        with pytest.raises(InvalidAnswerError):
            clean_links([bad])


def test_steps_are_trimmed_and_capped() -> None:
    steps = clean_steps([TaskStep(new_id(), "  one  "), TaskStep(new_id(), "two")])
    assert [s.title for s in steps] == ["one", "two"]
    with pytest.raises(InvalidAnswerError):
        clean_steps([TaskStep(new_id(), "s")] * (STEPS_MAX + 1))


def test_internal_link_rejects_control_chars_and_dot_segments() -> None:
    for bad in (
        "/\t/evil.test",
        "/\r/evil.test",
        "/\n/evil.test",
        "/../x",
        "/a/..",
        "/a b",
    ):
        with pytest.raises(InvalidAnswerError):
            clean_links([TaskLink("x", bad, "internal")])
