"""Agent steps: the ordered trace of what an answer did (AI-STEPS)."""

from app.shared.agent_steps import (
    AgentStep,
    StepKind,
    StepRecorder,
    StepStatus,
    current_steps,
    record_step,
    recording,
    step,
    steps_note,
)

import pytest


def test_recorder_keeps_order_and_finishes_steps() -> None:
    """AI-STEPS: steps are kept in the order they start, with status and timing."""
    recorder = StepRecorder()
    first = recorder.start(
        StepKind.READ_FILE, "Reviewed uploaded file", target="a.docx"
    )
    recorder.add(StepKind.WEB_SEARCH, "Searched the web")
    recorder.finish(first.id)

    steps = recorder.steps
    assert [s.kind for s in steps] == [StepKind.READ_FILE, StepKind.WEB_SEARCH]
    assert all(s.status is StepStatus.DONE for s in steps)
    assert steps[0].target == "a.docx"
    assert steps[0].duration_ms is not None and steps[0].duration_ms >= 0
    assert steps[0].started_at is not None


def test_listener_sees_every_update() -> None:
    """AI-STEPS: a live listener gets the running step and then the finished one."""
    seen: list[AgentStep] = []
    recorder = StepRecorder(listener=seen.append)
    started = recorder.start(StepKind.RETRIEVE, "Searched the sources")
    recorder.finish(started.id, StepStatus.FAILED)

    assert [s.status for s in seen] == [StepStatus.RUNNING, StepStatus.FAILED]
    assert seen[0].id == seen[1].id


def test_pop_updates_drains_the_live_queue() -> None:
    """AI-STEPS: a stream reads each update once."""
    recorder = StepRecorder()
    recorder.add(StepKind.TOOL, "Opened the plan view")
    assert len(recorder.pop_updates()) == 1
    assert recorder.pop_updates() == []
    assert len(recorder.steps) == 1


def test_take_returns_and_clears_the_steps() -> None:
    """AI-STEPS: the first stored answer of a turn carries the steps, not later ones."""
    recorder = StepRecorder()
    recorder.add(StepKind.CREATE, "Created plan")
    assert [s.label for s in recorder.take()] == ["Created plan"]
    assert recorder.take() == []


def test_record_step_without_recorder_is_a_no_op() -> None:
    """AI-STEPS: pipeline code may emit steps when nobody records them."""
    assert current_steps() is None
    record_step(StepKind.WEB_SEARCH, "Searched the web")


async def test_step_context_records_success_and_failure() -> None:
    """AI-STEPS: `step()` marks a step failed when its body raises."""
    recorder = StepRecorder()
    with recording(recorder):
        async with step(StepKind.RETRIEVE, "hop 1"):
            pass
        with pytest.raises(RuntimeError):
            async with step(StepKind.RETRIEVE, "hop 2"):
                raise RuntimeError("boom")
        record_step(StepKind.TOOL, "done")
    assert current_steps() is None
    assert [s.status for s in recorder.steps] == [
        StepStatus.DONE,
        StepStatus.FAILED,
        StepStatus.DONE,
    ]


def test_steps_note_is_compact() -> None:
    """AI-STEPS: the model sees at most a one-line note, never the full trace."""
    recorder = StepRecorder()
    recorder.add(StepKind.READ_FILE, "Reviewed uploaded file", target="x.docx")
    recorder.add(StepKind.WEB_SEARCH, "Searched the web")
    note = steps_note(recorder.steps)
    assert note.count("\n") == 0
    assert "x.docx" in note
    assert steps_note([]) == ""


def test_label_and_target_are_clipped() -> None:
    """AI-STEPS: stored steps stay small."""
    recorder = StepRecorder()
    made = recorder.add(StepKind.TOOL, "x" * 500, target="y" * 500)
    assert len(made.label) <= 120
    assert made.target is not None and len(made.target) <= 200
