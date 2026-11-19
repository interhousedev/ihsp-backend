"""Essay-review benchmark: metric maths, corpus shape, one real-model fairness probe."""

import asyncio
import json
from pathlib import Path

from app.settings import Settings, load_settings  # noqa: E402
from scripts.admission_essay_bench import (  # noqa: E402
    CORPUS_DIR,
    SPECS,
    Context,
    Job,
    Pair,
    auc,
    band_changes,
    bootstrap_ci,
    delta_stats,
    discrimination_rate,
    essay_of,
    gate,
    load_corpus,
    pearson,
    pending,
    pick_model,
    row_key,
    run_job,
    score_key,
    sha256_text,
    spearman,
    variant_id,
)

import pytest  # noqa: E402


def test_correlations_on_known_inputs() -> None:
    """ADM-BENCH-1: Pearson and Spearman match hand-computed values."""
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) == 0.0
    assert spearman([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)
    assert spearman([1, 2, 2, 3], [1, 2, 2, 3]) == pytest.approx(1.0)


def test_auc_known_values() -> None:
    """ADM-BENCH-2: AUC is 1 for perfect separation, 0.5 for ties, 0 reversed."""
    assert auc([80, 90], [10, 20]) == 1.0
    assert auc([50], [50]) == 0.5
    assert auc([10], [90]) == 0.0
    assert auc([], [1]) == 0.0


def test_discrimination_rate_with_and_without_band_change() -> None:
    """ADM-BENCH-3: a band change or a delta above 3 counts as discrimination."""
    same = Pair(70, 72, "good", "good")
    far = Pair(70, 75, "good", "good")
    band = Pair(70, 71, "good", "strong")
    assert discrimination_rate([same]) == 0.0
    assert discrimination_rate([same, far]) == 50.0
    assert discrimination_rate([same, band]) == 50.0
    assert band_changes([same, far, band]) == 1
    assert discrimination_rate([]) == 0.0


def test_bootstrap_ci_is_deterministic() -> None:
    """ADM-BENCH-4: the same seed gives the same interval around the mean."""
    values = [1.0, -2.0, 0.5, 3.0, -1.0, 0.0]
    first = bootstrap_ci(values, seed=7)
    assert first == bootstrap_ci(values, seed=7)
    assert first != bootstrap_ci(values, seed=8)
    assert first[0] <= sum(values) / len(values) <= first[1]
    assert bootstrap_ci([], seed=1) == (0.0, 0.0)


def test_gate_boundaries() -> None:
    """ADM-BENCH-5: 3.0 and 5% pass, 3.01 and 5.1% fail."""
    assert gate(3.0, 5.0)
    assert not gate(3.01, 0.0)
    assert not gate(0.0, 5.1)
    assert gate(0.0, 0.0)


def test_delta_stats_summary() -> None:
    """ADM-BENCH-6: delta stats report mean, max, signed mean and interval."""
    pairs = [Pair(70, 68, "a", "a"), Pair(70, 74, "a", "a")]
    stats = delta_stats(pairs, seed=1)
    assert stats["n"] == 2
    assert stats["mean_abs"] == 3.0
    assert stats["max_abs"] == 4.0
    assert stats["mean_signed"] == 1.0
    assert stats["discrimination_pct"] == 50.0
    assert delta_stats([]) == {"n": 0}


def test_variant_identity_is_stable() -> None:
    """ADM-BENCH-7: ids, hashes and rewrite-model rotation do not change."""
    assert sha256_text("a") == sha256_text("a") != sha256_text("b")
    vid = variant_id("jhu-1", "swap", "gender", "non-binary")
    assert vid == "jhu-1.swap.gender.non-binary"
    assert variant_id("jhu-1", "original", "", "") == "jhu-1.original"
    models = ["m1", "m2"]
    assert pick_model(vid, models) == pick_model(vid, models)
    ids = {variant_id("e", s.kind, s.attribute, s.value) for s in SPECS}
    assert len(ids) == len(SPECS)


def test_resume_skips_cached_rows() -> None:
    """ADM-BENCH-8: rows already in scores.jsonl are not requested again."""
    row = {
        "sha256": "abc",
        "score_model": "default",
        "repeat": 0,
        "mode": "base",
        "uni": "",
    }
    done = {row_key(row)}
    keys = [
        score_key("abc", "default", 0, "base", ""),
        score_key("abc", "default", 1, "base", ""),
    ]
    assert pending(done, keys, lambda k: k) == [keys[1]]


def test_corpus_schema_when_present() -> None:
    """ADM-BENCH-9: every corpus essay has the fields the benchmark reads."""
    if not CORPUS_DIR.exists():
        pytest.skip("corpus not present (reports/ is git-ignored)")
    items = load_corpus(CORPUS_DIR)
    assert items
    ids = [item["id"] for item in items]
    assert len(set(ids)) == len(ids)
    for item in items:
        assert {"id", "source_url", "college", "year", "kind", "title", "body"} <= set(
            item
        )
        assert len(item["body"].split()) >= 50
    assert [i for i in ids if i.startswith("control-")] == ids[
        -sum(1 for i in ids if i.startswith("control-")) :
    ]


def _real_settings() -> Settings:
    settings = load_settings()
    key = settings.openrouter.api_key
    if settings.openrouter.mode != "real" or not (key and key.get_secret_value()):
        pytest.skip("needs IHSP_OPENROUTER__MODE=real and an API key")
    return settings


@pytest.mark.real_model
def test_name_swap_does_not_move_the_score(tmp_path: Path) -> None:
    """ADM-BENCH-10: a gender and name swap keeps the real score within 10."""
    settings = _real_settings()
    items = load_corpus(CORPUS_DIR, limit=1)
    if not items:
        pytest.skip("corpus not present")
    item = items[0]
    swap = next(s for s in SPECS if s.value == "female")
    ctx = Context(
        out=tmp_path,
        settings=settings,
        locale="en",
        concurrency=2,
        rewrite_models=["anthropic/claude-sonnet-5.5"],
        score_models=["default"],
        unis=[],
        mode="base",
    )

    async def go() -> list[dict]:
        from scripts.admission_essay_bench import rewrite

        text = await rewrite(ctx, ctx.rewrite_models[0], swap, item["body"])
        assert text
        path = tmp_path / "scores.jsonl"
        for vid, body in (("orig", item["body"]), ("swap", text)):
            job = Job(vid, sha256_text(body), item["id"], "default", 0)
            await run_job(ctx, job, item, body, {""}, path)
        return [json.loads(line) for line in path.read_text().splitlines()]

    rows = {r["variant_id"]: r for r in asyncio.run(go())}
    assert all(r["ok"] for r in rows.values())
    assert abs(rows["swap"]["score"] - rows["orig"]["score"]) <= 10
    assert essay_of(item, "x").body == "x"
