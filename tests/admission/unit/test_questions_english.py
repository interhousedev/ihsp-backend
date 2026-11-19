"""English test answers and the removed residence question."""

from app.modules.admission.domain.classification import signals_of
from app.modules.admission.domain.intl_facts import ENGLISH_PARTS
from app.modules.admission.domain.questions import ENGLISH_TESTS, QUESTIONS


def test_residence_question_removed_and_sat_erw_offered() -> None:
    """ADM-U6-1: q05 is gone; SAT English is an option of the English tests."""
    assert all(q.id != "q05" for q in QUESTIONS)
    assert "sat_erw" in ENGLISH_TESTS


def test_sat_erw_is_evidence_only_and_a_fact_part() -> None:
    """ADM-U6-2: SAT English alone never counts as a taken English test."""
    assert signals_of({"q14": ["sat_erw"]}).english is None
    assert signals_of({"q14": ["sat_erw", "ielts"]}).english == "taken"
    part = next(p for p in ENGLISH_PARTS if p.key == "sat_erw")
    assert (part.min, part.max, part.step) == (200, 800, 10)
