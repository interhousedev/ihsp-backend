"""Test scores domain: range validation, totals, best result and superscore."""

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Any

from app.modules.admission.domain.errors import (
    InvalidProofUrlError,
    ScoreInvalidError,
)
from app.modules.admission.domain.test_scores import (
    ScoreEntry,
    ScoreEntryDraft,
    ScoreTest,
    build_scores,
    compute_total,
    summarise,
    to_json,
    validate_definition,
    validate_entry,
)
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.admission.unit.score_defs import (
    ACT,
    ALEVEL,
    AP,
    CERT,
    DUOLINGO,
    IELTS,
    SAT,
    TOEFL,
    make_test,
    sec,
)

import pytest

DAY = dt.date(2027, 3, 1)


def _draft(test: ScoreTest, **kw: Any) -> ScoreEntryDraft:
    base: dict[str, Any] = {"test_id": test.id, "status": "score_received"}
    return ScoreEntryDraft(**{**base, **kw})


def _entry(test: ScoreTest, sections: dict, total: Any, day: int = 1) -> ScoreEntry:
    return ScoreEntry(
        id=new_id(),
        student_id=new_id(),
        test_id=test.id,
        status="score_received",
        test_date=DAY + dt.timedelta(days=day),
        registration_deadline=None,
        label=None,
        level=None,
        sections={k: Decimal(v) for k, v in sections.items()},
        total=Decimal(total) if total is not None else None,
        certificate_document_id=None,
        verification_url=None,
        send_note=None,
        is_official=False,
        verified_by=None,
        verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_sat_total_is_sum_and_ranges_are_enforced() -> None:
    sections, total = build_scores(SAT, {"ebrw": 700, "math": 750}, None)
    assert total == Decimal(1450) and sections["math"] == Decimal(750)
    for bad in ({"ebrw": 190, "math": 700}, {"ebrw": 805, "math": 700}):
        with pytest.raises(ScoreInvalidError):
            build_scores(SAT, bad, None)
    with pytest.raises(ScoreInvalidError) as err:
        build_scores(SAT, {"ebrw": 705, "math": 700}, None)  # step 10
    assert err.value.params == {"field": "ebrw", "min": 200, "max": 800}


def test_unknown_section_bool_and_text_rejected() -> None:
    for bad in ({"x": 5}, {"ebrw": True}, {"ebrw": "abc"}, {"ebrw": float("nan")}):
        with pytest.raises(ScoreInvalidError):
            build_scores(SAT, bad, None)


def test_act_composite_rounds_half_up() -> None:
    _, total = build_scores(
        ACT, {"english": 30, "math": 31, "reading": 30, "science": 30}, 1
    )
    assert total == Decimal(30)  # mean 30.25 -> 30; client total ignored
    _, total = build_scores(
        ACT, {"english": 30, "math": 31, "reading": 31, "science": 30}, 1
    )
    assert total == Decimal(31)  # mean 30.5 -> 31


def test_ielts_overall_rounds_to_half_band() -> None:
    parts = lambda *v: dict(zip("lrws", v, strict=True))  # noqa: E731
    assert compute_total(
        IELTS, {k: Decimal(str(x)) for k, x in parts(6.5, 6.5, 6, 6).items()}
    ) == Decimal("6.5")
    assert compute_total(
        IELTS, {k: Decimal(str(x)) for k, x in parts(6, 6, 6, 6.5).items()}
    ) == Decimal("6")
    assert compute_total(
        IELTS, {k: Decimal(str(x)) for k, x in parts(7, 7, 6.5, 6.5).items()}
    ) == Decimal("7")
    with pytest.raises(ScoreInvalidError):
        build_scores(IELTS, parts(6.25, 6, 6, 6), None)
    with pytest.raises(ScoreInvalidError):
        build_scores(IELTS, parts(9.5, 6, 6, 6), None)


def test_toefl_sum_and_partial_sections_need_total() -> None:
    _, total = build_scores(TOEFL, {"r": 28, "l": 29, "s": 26, "w": 27}, None)
    assert total == Decimal(110)
    sections, total = build_scores(TOEFL, {"r": 28}, 100)  # official total only
    assert total == Decimal(100) and sections == {"r": Decimal(28)}
    with pytest.raises(ScoreInvalidError):
        build_scores(TOEFL, {"r": 28}, 121)
    with pytest.raises(ScoreInvalidError):
        build_scores(TOEFL, {}, None)


def test_manual_totals() -> None:
    assert build_scores(DUOLINGO, {}, 125)[1] == Decimal(125)
    with pytest.raises(ScoreInvalidError):
        build_scores(DUOLINGO, {}, None)
    with pytest.raises(ScoreInvalidError):
        build_scores(DUOLINGO, {}, 127)  # step 5
    with pytest.raises(ScoreInvalidError):
        build_scores(AP, {}, 6)


def test_choice_total_for_a_levels() -> None:
    assert build_scores(ALEVEL, {}, "A*")[1] == "A*"
    with pytest.raises(ScoreInvalidError):
        build_scores(ALEVEL, {}, "F")
    with pytest.raises(ScoreInvalidError):
        build_scores(ALEVEL, {}, 5)


def test_certificate_has_no_scores() -> None:
    assert build_scores(CERT, {}, None) == ({}, None)
    d = _draft(CERT, label="Olympiad", level="national")
    assert validate_entry(CERT, d) == ({}, None)
    with pytest.raises(ScoreInvalidError):
        validate_entry(CERT, _draft(CERT, level="national"))  # label required
    with pytest.raises(ScoreInvalidError):
        validate_entry(CERT, _draft(CERT, label="Olympiad"))  # level required


def test_scores_only_on_received_status() -> None:
    ok = ScoreEntryDraft(test_id=SAT.id, status="planned", test_date=DAY)
    assert validate_entry(SAT, ok) == ({}, None)
    for kw in (
        {"sections": {"ebrw": 700}},
        {"total": 1000},
        {"certificate_document_id": new_id()},
        {"verification_url": "https://example.org/r"},
    ):
        with pytest.raises(ScoreInvalidError):
            validate_entry(SAT, dataclasses.replace(ok, **kw))


def test_dates_url_and_label_rules() -> None:
    with pytest.raises(ScoreInvalidError):
        validate_entry(
            SAT,
            ScoreEntryDraft(
                test_id=SAT.id,
                status="planned",
                test_date=DAY,
                registration_deadline=DAY + dt.timedelta(days=1),
            ),
        )
    with pytest.raises(ScoreInvalidError):
        validate_entry(AP, _draft(AP, total=5))  # subject label required
    with pytest.raises(InvalidProofUrlError):
        validate_entry(
            DUOLINGO, _draft(DUOLINGO, total=100, verification_url="http://x.org")
        )
    with pytest.raises(ScoreInvalidError):
        validate_entry(
            SAT, _draft(SAT, sections={"ebrw": 700, "math": 700}, send_note="x" * 501)
        )
    s, t = validate_entry(
        DUOLINGO, _draft(DUOLINGO, total=100, verification_url="https://x.org/c")
    )
    assert (s, t) == ({}, Decimal(100))


def test_best_and_superscore_across_sittings() -> None:
    a = _entry(SAT, {"ebrw": 700, "math": 650}, 1350, 1)
    b = _entry(SAT, {"ebrw": 680, "math": 720}, 1400, 2)
    s = summarise(SAT, [a, b])
    assert s.best_entry_id == b.id and s.best_total == Decimal(1400)
    assert s.superscore_sections == {"ebrw": Decimal(700), "math": Decimal(720)}
    assert s.superscore_total == Decimal(1420)


def test_superscore_needs_two_sittings_and_flag() -> None:
    a = _entry(SAT, {"ebrw": 700, "math": 650}, 1350)
    s = summarise(SAT, [a])
    assert s.best_total == Decimal(1350) and s.superscore_total is None
    x = _entry(TOEFL, {"r": 20, "l": 20, "s": 20, "w": 20}, 80, 1)
    y = _entry(TOEFL, {"r": 25, "l": 10, "s": 20, "w": 20}, 75, 2)
    assert summarise(TOEFL, [x, y]).superscore_total is None  # not a superscore test


def test_act_superscore_recomputes_composite() -> None:
    a = _entry(ACT, {"english": 30, "math": 28, "reading": 30, "science": 30}, 30)
    b = _entry(ACT, {"english": 28, "math": 33, "reading": 29, "science": 30}, 30, 2)
    s = summarise(ACT, [a, b])
    assert s.superscore_total == Decimal(31)  # 30,33,30,30 -> mean 30.75 -> 31


def test_unreceived_entries_ignored_and_labelled_tests_have_no_best() -> None:
    planned = dataclasses.replace(_entry(SAT, {}, None), status="planned")
    assert summarise(SAT, [planned]).best_entry_id is None
    ap = _entry(AP, {}, 5)
    assert summarise(AP, [ap]).best_entry_id is None


def test_choice_best_is_the_better_grade() -> None:
    grades = dataclasses.replace(ALEVEL, needs_label=False)
    a = dataclasses.replace(_entry(grades, {}, 1), total="B")
    b = dataclasses.replace(_entry(grades, {}, 1), total="A")
    assert summarise(grades, [a, b]).best_total == "A"


def test_to_json_roundtrip_types() -> None:
    assert to_json(Decimal("6.5")) == 6.5 and to_json(Decimal("120")) == 120
    assert to_json("A*") == "A*" and to_json(None) is None


def test_definition_validation() -> None:
    validate_definition(SAT)
    for bad in (
        dataclasses.replace(SAT, key="Bad Key"),
        dataclasses.replace(SAT, names={"en": "x"}),
        dataclasses.replace(SAT, sections=()),  # sum needs sections
        dataclasses.replace(SAT, total=None),
        dataclasses.replace(DUOLINGO, superscore=True),
        dataclasses.replace(CERT, total=sec("t", "1", "2")),
        dataclasses.replace(SAT, sections=(sec("a", "10", "5"), sec("b", "0", "5"))),
        dataclasses.replace(SAT, sections=(sec("a", "0", "5"), sec("a", "0", "5"))),
        make_test(
            "ok", (), sec("t", "0", "10", "3"), "manual"
        ),  # span not a step multiple
    ):
        with pytest.raises(ScoreInvalidError):
            validate_definition(bad)
