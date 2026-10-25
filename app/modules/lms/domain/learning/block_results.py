"""Results of H5P and interactive video blocks, kept in the student's step state.

They live in ``StepState.cards`` under ``block:<block id>`` (card ids never contain
``:``), so no extra table is needed; the flash card logic looks cards up by id and
never sees these keys.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.modules.lms.domain.step_content import Interaction, InteractiveVideoBlock

RESULT_PREFIX: Final = "block:"
XAPI_COMPLETED: Final = "http://adlnet.gov/expapi/verbs/completed"
XAPI_ANSWERED: Final = "http://adlnet.gov/expapi/verbs/answered"


def result_key(block_id: str) -> str:
    """Return the ``cards`` key of a block result."""
    return f"{RESULT_PREFIX}{block_id}"


def stored_result(
    states: Mapping[str, Mapping[str, Any]], block_id: str
) -> Mapping[str, Any] | None:
    """Return the stored result of a block, if any."""
    return states.get(result_key(block_id))


def passed_block_ids(states: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Return the H5P and interactive video blocks the student has finished.

    An H5P block is done when it is passed (completed and above its threshold);
    an interactive video when every question was answered.
    """
    done: set[str] = set()
    for key, record in states.items():
        if not key.startswith(RESULT_PREFIX):
            continue
        ok = (
            record.get("passed")
            if record.get("kind") == "h5p"
            else record.get("completed")
        )
        if ok:
            done.add(key[len(RESULT_PREFIX) :])
    return done


@dataclass(frozen=True, slots=True)
class H5PResult:
    """The score of a whole H5P content, mapped from an xAPI statement."""

    score: float
    max_score: float
    completed: bool

    @property
    def pct(self) -> float:
        """Return the score in percent (100 for content without a score)."""
        return 100.0 if self.max_score <= 0 else 100.0 * self.score / self.max_score


def map_xapi(statement: Mapping[str, Any]) -> H5PResult | None:
    """Map an H5P xAPI statement to a result of the whole content.

    Only ``completed`` and ``answered`` statements of the root content count:
    sub-contents (a question inside a question set or a video) send their own
    ``answered`` with a parent in ``context.contextActivities``, and those are
    ignored. Statements without a result are ignored too.
    """
    verb = (statement.get("verb") or {}).get("id")
    if verb not in (XAPI_COMPLETED, XAPI_ANSWERED):
        return None
    context = statement.get("context") or {}
    if (context.get("contextActivities") or {}).get("parent"):
        return None
    result = statement.get("result")
    if not isinstance(result, Mapping):
        return None
    score = result.get("score") or {}
    raw = _number(score.get("raw"))
    top = _number(score.get("max"))
    if raw is None and (scaled := _number(score.get("scaled"))) is not None:
        raw, top = scaled * 100, 100.0
    raw, top = max(0.0, raw or 0.0), max(0.0, top or 0.0)
    completed = verb == XAPI_COMPLETED or bool(result.get("completion"))
    return H5PResult(
        score=min(raw, top) if top else raw, max_score=top, completed=completed
    )


def merge_h5p(
    previous: Mapping[str, Any] | None, result: H5PResult, passing_pct: float
) -> dict[str, Any]:
    """Return the stored record: the best score so far, completion is sticky."""
    best = dict(previous or {})
    better = previous is None or result.pct >= float(best.get("pct", 0))
    if better:
        best.update(score=result.score, max_score=result.max_score, pct=result.pct)
    best["kind"] = "h5p"
    best["completed"] = bool(best.get("completed")) or result.completed
    best["passed"] = bool(best["completed"]) and float(best["pct"]) >= passing_pct
    return best


def is_correct(interaction: Interaction, option_ids: Sequence[str]) -> bool:
    """Return True when the chosen options are exactly the correct ones.

    A question without a correct option accepts any answer (a poll).
    """
    correct = {option.id for option in interaction.options if option.correct}
    if not correct:
        return bool(option_ids)
    return set(option_ids) == correct


def record_answer(
    block: InteractiveVideoBlock,
    previous: Mapping[str, Any] | None,
    interaction_id: str,
    option_ids: Sequence[str],
) -> dict[str, Any]:
    """Return the stored record of the block with one more answer.

    The first answer of an interaction counts; later ones are kept for review but
    do not change the score.

    Raises:
        KeyError: The block has no question with this id.
    """
    by_id = {i.id: i for i in block.interactions if i.kind == "question"}
    interaction = by_id[interaction_id]
    answers = dict((previous or {}).get("answers", {}))
    if interaction_id not in answers:
        answers[interaction_id] = {
            "option_ids": list(option_ids),
            "correct": is_correct(interaction, option_ids),
        }
    return {"kind": "interactive_video", "answers": answers, **summary(block, answers)}


def summary(
    block: InteractiveVideoBlock, answers: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Return score, max score and completion of the answered questions."""
    questions = [i for i in block.interactions if i.kind == "question"]
    score = sum(i.points for i in questions if answers.get(i.id, {}).get("correct"))
    return {
        "score": score,
        "max_score": sum(i.points for i in questions),
        "completed": all(i.id in answers for i in questions),
    }


def _number(value: object) -> float | None:
    """Return a JSON number as float (booleans are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
