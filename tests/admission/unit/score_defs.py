"""Test definitions shared by the test-score tests."""

from decimal import Decimal

from app.modules.admission.domain.test_scores import ScoreTest, SectionDef
from app.shared.ids import new_id


def names(en: str) -> dict[str, str]:
    """Return the same name in every locale."""
    return {"uz": en, "ru": en, "en": en}


def sec(
    key: str, lo: str, hi: str, step: str = "1", choices: tuple[str, ...] = ()
) -> SectionDef:
    """Build a section definition."""
    return SectionDef(key, names(key), Decimal(lo), Decimal(hi), Decimal(step), choices)


def make_test(
    key: str,
    sections: tuple[SectionDef, ...],
    total: SectionDef | None,
    mode: str,
    **extra: object,
) -> ScoreTest:
    """Build a test definition."""
    return ScoreTest(
        id=new_id(),
        key=key,
        names=names(key),
        sections=sections,
        total=total,
        total_mode=mode,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


SAT = make_test(
    "sat",
    (sec("ebrw", "200", "800", "10"), sec("math", "200", "800", "10")),
    sec("total", "400", "1600", "10"),
    "sum",
    superscore=True,
)
ACT = make_test(
    "act",
    tuple(sec(k, "1", "36") for k in ("english", "math", "reading", "science")),
    sec("composite", "1", "36"),
    "mean_int",
    superscore=True,
)
IELTS = make_test(
    "ielts",
    tuple(sec(k, "0", "9", "0.5") for k in ("l", "r", "w", "s")),
    sec("overall", "0", "9", "0.5"),
    "mean_half",
)
TOEFL = make_test(
    "toefl",
    tuple(sec(k, "0", "30") for k in ("r", "l", "s", "w")),
    sec("total", "0", "120"),
    "sum",
)
DUOLINGO = make_test("duolingo", (), sec("total", "10", "160", "5"), "manual")
AP = make_test("ap", (), sec("score", "1", "5"), "manual", needs_label=True)
ALEVEL = make_test(
    "a_level",
    (),
    sec("grade", "0", "0", choices=("A*", "A", "B", "C", "D", "E")),
    "manual",
    needs_label=True,
)
CERT = make_test("certificate", (), None, "none", needs_label=True, needs_level=True)
