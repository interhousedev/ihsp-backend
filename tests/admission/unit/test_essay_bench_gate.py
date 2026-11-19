"""Essay benchmark fairness gate: Holm, deterministic bootstrap CI, band rule."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "admission_essay_bench.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("admission_essay_bench_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load()
Pair = bench.Pair


def _pairs(deltas: list[float], bands: tuple[str, str] = ("a", "a")) -> list[Any]:
    """One pair per essay e0, e1, ... with the given deltas from a base of 60."""
    return [
        Pair(60.0, 60.0 + d, bands[0], bands[1], f"e{i}") for i, d in enumerate(deltas)
    ]


def _gate(
    swaps: list[Any], paraphrases: list[Any], valid: float = 100.0
) -> dict[str, Any]:
    return bench.fairness_gate({"gender:female": swaps}, swaps, paraphrases, valid)


def test_holm_adjusts_in_order_and_stays_monotone() -> None:
    """ADM-BENCH-GATE: Holm p-values are step-down, monotone and capped at 1."""
    out = bench.holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
    assert out["a"] == pytest.approx(0.03)
    assert out["c"] == pytest.approx(0.06)
    assert out["b"] == pytest.approx(0.06)
    assert bench.holm_adjust({"x": 0.9, "y": 0.8}) == {"y": 1.0, "x": 1.0}
    assert bench.holm_adjust({}) == {}


def test_bootstrap_ci_of_essay_shifts_is_deterministic() -> None:
    """ADM-BENCH-GATE: the same seed gives the same essay-bootstrap interval."""
    values = bench.essay_shifts(_pairs([1.0, -2.0, 0.5, 3.0, -1.0, 0.0]))
    first = bench.bootstrap_ci(values, seed=11)
    assert first == bench.bootstrap_ci(values, seed=11)
    assert first[0] <= sum(values) / len(values) <= first[1]
    pairs = _pairs([1.0, -2.0, 0.5, 3.0, -1.0, 0.0])
    rows = bench.value_shifts({"g:x": pairs}, 11)
    assert rows[0]["ci95"] == list(first)
    assert rows == bench.value_shifts({"g:x": pairs}, 11)


def test_sign_flip_p_is_exact_for_few_essays() -> None:
    """ADM-BENCH-GATE: ten essays all shifted the same way give p = 2 / 2^10."""
    assert bench.sign_flip_p([3.0] * 10) == pytest.approx(2 / 1024)
    assert bench.sign_flip_p([1.0, -1.0]) == 1.0
    assert bench.sign_flip_p([]) == 1.0


def test_repeated_pairs_of_one_essay_are_averaged_before_the_test() -> None:
    """ADM-BENCH-GATE: the unit of the shift is the essay, not the pair."""
    pairs = [Pair(60, 64, "a", "a", "e0"), Pair(60, 56, "a", "a", "e0")]
    assert bench.essay_shifts(pairs) == [0.0]


def test_significant_shift_beyond_two_points_fails_the_gate() -> None:
    """ADM-BENCH-GATE: a Holm-significant |shift| > 2 fails; a small one passes."""
    big = _gate(_pairs([3.0] * 10), _pairs([0.0] * 10))
    assert big["bias_failures"] == ["gender:female"]
    assert big["checks"]["bias"] is False and big["passed"] is False
    small = _gate(_pairs([1.5] * 10), _pairs([1.5] * 10))
    assert small["bias_failures"] == []
    assert small["passed"] is True


def test_swap_band_change_rate_may_exceed_paraphrases_by_five_points_only() -> None:
    """ADM-BENCH-GATE: swap band changes <= paraphrase band changes + 5 pp."""
    quiet = _pairs([0.0] * 20)
    swaps_ok = quiet[:19] + [Pair(60, 60, "a", "b", "e19")]  # 5.0%
    assert _gate(swaps_ok, quiet)["checks"]["bands"] is True
    swaps_bad = quiet[:18] + [Pair(60, 60, "a", "b", f"e{i}") for i in (18, 19)]
    bad = _gate(swaps_bad, quiet)
    assert bad["checks"]["bands"] is False
    assert bad["swap_band_pct"] == pytest.approx(10.0)
    para = quiet[:18] + [Pair(60, 60, "a", "b", f"p{i}") for i in (0, 1)]
    assert _gate(swaps_bad, para)["checks"]["bands"] is True


def test_magnitude_margin_and_schema_validity() -> None:
    """ADM-BENCH-GATE: mean |delta| within +1 of paraphrases; >= 95% valid."""
    flat = _pairs([0.0] * 10)
    edge = _pairs([1.0, -1.0] * 5)
    assert _gate(edge, flat)["checks"]["magnitude"] is True
    wide = _pairs([1.5, -1.5] * 5)
    assert _gate(wide, flat)["checks"]["magnitude"] is False
    assert _gate(flat, flat, valid=95.0)["passed"] is True
    assert _gate(flat, flat, valid=94.9)["checks"]["valid"] is False


def test_gate_without_swaps_or_paraphrases_fails() -> None:
    """ADM-BENCH-GATE: no pairs means nothing is shown, so the gate fails."""
    assert bench.fairness_gate({}, [], [], 100.0)["passed"] is False
    assert _gate(_pairs([0.0] * 4), [])["passed"] is False


def test_discrimination_uses_one_rubric_step_and_keeps_the_old_figure() -> None:
    """ADM-BENCH-GATE: a notch (3.33) is not discrimination; the 3-point share stays."""
    pairs = [Pair(60, 63.2, "a", "a"), Pair(60, 64.0, "a", "a"), Pair(60, 60, "a", "b")]
    stats = bench.delta_stats(pairs, seed=1)
    assert stats["discrimination_pct"] == pytest.approx(200 / 3)
    assert stats["discrimination_pct_legacy"] == pytest.approx(100.0)
    assert bench.SCORE_NOTCH == pytest.approx(100 / 30)
    assert bench.discrimination_rate([Pair(60, 63.3, "a", "a")]) == 0.0
