"""Coach domain (spec 2-lms-duo-ai-tutor.md, section 2.4), pure functions.

The implementation must provide `app.modules.lms.domain.learning.coach` with:
  CoachMode (ask|hint|remediate|recap), CoachOutcome (resolved|abandoned|escalated),
  KeyStatus (draft|approved), Misconception(pattern, nudge),
  SolutionKey(step_id, block_id, question_id, steps, misconceptions, status,
    answers=[]  # final answers for the output filter only; never in prompt_steps),
  TutorTurn(session_id, role, text, hint_level, citations, created_at),
  TutorSession.open(id, enrollment_id, step_id, block_id, mode, opened_at)
    .record_turn(role, text, hint_level, *, attempts_made, attempts_left, at) ->
    TutorTurn
    .close(outcome, at); attributes: turns, hint_level (highest so far), closed_at,
    outcome
  HintLevelRegressionError, HintLockedError, SessionClosedError (all DomainError)
  prompt_steps(keys) -> only approved keys' steps, never an answer
  leaks_answer(reply, answers) -> bool (output post-filter, case/space-insensitive)
  MAX_HINT_LEVEL == 3
Boring choices: level 0 = plain chat turn; level 3 needs attempts_made >= 1 or
attempts_left == 0; a closed session rejects turns; errors are raised, not clamped.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.lms.domain.learning.coach import (
    MAX_HINT_LEVEL,
    CoachMode,
    CoachOutcome,
    HintLevelRegressionError,
    HintLockedError,
    KeyStatus,
    Misconception,
    SessionClosedError,
    SolutionKey,
    TutorSession,
    leaks_answer,
    prompt_steps,
)

import pytest

T0 = datetime(2026, 11, 27, 9, tzinfo=UTC)


def _session(mode: CoachMode = CoachMode.HINT) -> TutorSession:
    return TutorSession.open(
        id=uuid4(),
        enrollment_id=uuid4(),
        step_id=uuid4(),
        block_id="quiz",
        mode=mode,
        opened_at=T0,
    )


def _turn(s: TutorSession, level: int, *, made: int = 1, left: int | None = 2) -> None:
    s.record_turn(
        "tutor",
        "msg",
        level,
        attempts_made=made,
        attempts_left=left,
        at=T0 + timedelta(minutes=1),
    )


def test_a_new_session_is_open_with_no_turns() -> None:
    s = _session()
    assert (s.closed_at, s.outcome, s.turns, s.hint_level) == (None, None, [], 0)


def test_hint_level_is_monotonic() -> None:
    """Kestin: one step at a time; the ladder never goes back down."""
    s = _session()
    _turn(s, 1)
    _turn(s, 2)
    _turn(s, 2)
    with pytest.raises(HintLevelRegressionError):
        _turn(s, 1)
    assert s.hint_level == 2


def test_level_cannot_skip_beyond_the_max() -> None:
    s = _session()
    with pytest.raises(ValueError):
        _turn(s, MAX_HINT_LEVEL + 1)


def test_level_3_needs_an_attempt_first() -> None:
    """Think first: no worked step before the learner tried once."""
    s = _session()
    with pytest.raises(HintLockedError):
        _turn(s, 3, made=0, left=2)
    assert s.turns == []


def test_level_3_after_one_attempt_is_allowed() -> None:
    s = _session()
    _turn(s, 3, made=1, left=2)
    assert s.hint_level == 3


def test_level_3_when_attempts_are_exhausted_is_allowed() -> None:
    s = _session(CoachMode.REMEDIATE)
    _turn(s, 3, made=0, left=0)
    assert s.hint_level == 3


@pytest.mark.parametrize("level", [0, 1, 2])
def test_levels_below_3_never_need_an_attempt(level: int) -> None:
    s = _session()
    _turn(s, level, made=0, left=3)
    assert s.hint_level == level


def test_learner_turns_do_not_move_the_ladder() -> None:
    s = _session()
    s.record_turn("learner", "help", 0, attempts_made=0, attempts_left=3, at=T0)
    assert s.hint_level == 0


def test_closing_records_outcome_and_blocks_more_turns() -> None:
    s = _session()
    s.close(CoachOutcome.RESOLVED, T0 + timedelta(minutes=5))
    assert (s.outcome, s.closed_at) == (
        CoachOutcome.RESOLVED,
        T0 + timedelta(minutes=5),
    )
    with pytest.raises(SessionClosedError):
        _turn(s, 1)
    with pytest.raises(SessionClosedError):
        s.close(CoachOutcome.ABANDONED, T0 + timedelta(minutes=6))


def _key(status: KeyStatus, steps: list[str]) -> SolutionKey:
    return SolutionKey(
        step_id=uuid4(),
        block_id="quiz",
        question_id="q1",
        steps=steps,
        misconceptions=[Misconception(pattern="adds", nudge="Check the sign")],
        status=status,
    )


def test_only_approved_keys_reach_the_prompt() -> None:
    """Pardos: AI drafts, the teacher approves; a draft is never used."""
    approved = _key(KeyStatus.APPROVED, ["isolate x", "divide by 2"])
    draft = _key(KeyStatus.DRAFT, ["SECRET draft step"])
    steps = prompt_steps([approved, draft])
    assert "isolate x" in steps and "divide by 2" in steps
    assert not any("SECRET" in s for s in steps)


def test_no_keys_means_no_steps() -> None:
    assert prompt_steps([]) == []
    assert prompt_steps([_key(KeyStatus.DRAFT, ["x"])]) == []


@pytest.mark.parametrize(
    ("reply", "leaks"),
    [
        ("The answer is 42.", True),
        ("so it is  FORTY-TWO", False),
        ("Try isolating x first.", False),
        ("x = 4 2", False),
        ("Result: 42", True),
    ],
)
def test_output_filter_blocks_replies_that_contain_a_final_answer(
    reply: str, leaks: bool
) -> None:
    """Bastani: the reply is compared with the answer keys before it is sent."""
    assert leaks_answer(reply, ["42"]) is leaks


def test_filter_is_case_and_space_insensitive_for_text_answers() -> None:
    assert leaks_answer("It is  Tashkent.", ["tashkent"])
    assert not leaks_answer("A big city", ["tashkent"])


def test_filter_ignores_empty_answers() -> None:
    assert not leaks_answer("anything", [""])
    assert not leaks_answer("anything", [])
