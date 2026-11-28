"""Scoring of the overall student rating."""

import datetime as dt
from uuid import uuid4

from app.modules.academic.domain.marks.overall_rating import (
    RatedCertificate,
    RatingInput,
    RatingWeights,
    rank,
    score_student,
)
from app.modules.academic.wiring_marks import rating_weights
from app.settings import RatingSettings

DAY = dt.date(2026, 10, 1)


def test_settings_defaults_equal_domain_defaults() -> None:
    assert rating_weights(RatingSettings()) == RatingWeights()


def test_base_only() -> None:
    b = score_student(RatingInput(uuid4(), "A"), RatingWeights())
    assert b.score == 100.0
    assert b.mark_average is None and b.marks_points == 0.0


def test_certificate_category_plus_level() -> None:
    cert = RatedCertificate("IMO", "olympiad", "International", DAY)
    unknown = RatedCertificate("X", None, "galactic", DAY)
    b = score_student(
        RatingInput(uuid4(), "A", certificates=[cert, unknown]), RatingWeights()
    )
    assert [c.points for c in b.certificates] == [20.0, 3.0]
    assert b.certificates[1].category == "other"
    assert b.score == 123.0


def test_marks_bonus_above_threshold_only() -> None:
    w = RatingWeights()
    good = score_student(RatingInput(uuid4(), "A", mark_sum=9, mark_count=2), w)
    poor = score_student(RatingInput(uuid4(), "A", mark_sum=5, mark_count=2), w)
    assert good.mark_average == 4.5 and good.marks_points == 30.0
    assert poor.marks_points == 0.0


def test_overlapping_absences_count_once_and_work_offs() -> None:
    subject = uuid4()
    other = uuid4()
    item = RatingInput(
        uuid4(),
        "A",
        platform_absences=[(subject, DAY), (subject, DAY)],
        emis_absences=[(subject, DAY), (other, DAY)],
        work_offs=3,
    )
    b = score_student(item, RatingWeights())
    assert b.absences == 3 and b.absence_points == -3.0
    assert b.work_off_points == -6.0
    assert b.score == 91.0


def test_score_never_negative() -> None:
    item = RatingInput(uuid4(), "A", work_offs=500)
    assert score_student(item, RatingWeights()).score == 0.0


def test_rank_shares_places() -> None:
    a, b, c = (RatingInput(uuid4(), "A") for _ in range(3))
    c = RatingInput(c.student_id, "A", work_offs=1)
    places = [p for p, _ in rank([c, a, b], RatingWeights())]
    assert places == [1, 1, 3]
