"""The AI input of the words and the alignment map: only mentor-visible answers."""

from app.modules.admission.application.words import answer_texts


def test_answer_texts_drop_answers_mentors_cannot_read() -> None:
    texts = answer_texts({"q04": "UZ", "q06": "yes", "q38": True, "q20": "Robots"})
    # q04/q06 are staff-only and q38 owner-only; mentors read the stored output.
    assert texts == {"q20": "Robots"}
