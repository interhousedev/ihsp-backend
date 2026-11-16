"""Golden-set evaluation of the admission item review (spec §13).

Runs every example of `tests/admission/eval/*.jsonl` through the real review
pipeline (prompt, model, projected-impact cap) and reports:

- agreement: share of graded dimensions within one grade of the expected band;
- schema validity: share of answers that parse into the review schema;
- latency p50 / p95 of a model call.

A real model is called only when `IHSP_OPENROUTER__MODE=real` and an API key is
configured; otherwise the script says so and exits 0 without calling anything.
It never prints settings or environment values.

    IHSP_ENV_FILE=.env.local uv run python scripts/admission_eval.py
    uv run python scripts/admission_eval.py --only act-en-01 --locale ru

The exit code is 1 when agreement or schema validity is below `THRESHOLD`.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.modules.admission.application.review import (  # noqa: E402
    ItemInput,
    ItemReviewService,
)
from app.modules.admission.application.review_rubric import (  # noqa: E402
    DIMENSIONS,
    POINTS,
)
from app.modules.admission.domain.items import Item  # noqa: E402
from app.modules.admission.infrastructure.ai.prompt_source import (  # noqa: E402
    BuiltinPrompts,
)
from app.modules.admission.infrastructure.ai_gateway import (  # noqa: E402
    GatewayStructuredAi,
)
from app.modules.admission.ports.items import Metric, ProfileWordsRef  # noqa: E402
from app.modules.ai.infrastructure.gateway_factory import (  # noqa: E402
    make_llm_gateway,
)
from app.modules.notebooks.application.llm import NotebookLlm  # noqa: E402
from app.settings import load_settings  # noqa: E402
from app.shared.clock import SystemClock  # noqa: E402
from app.shared.contracts.ai import AiInvalidOutputError  # noqa: E402
from app.shared.ids import new_id  # noqa: E402

EVAL_DIR = BACKEND / "tests" / "admission" / "eval"
THRESHOLD = 0.8
"""Minimum agreement (within ±1) and schema validity rate to pass."""


@dataclass(frozen=True, slots=True)
class Case:
    """One golden example."""

    id: str
    locale: str
    data: ItemInput
    expected: dict[str, tuple[str, str]]


def load_cases() -> list[Case]:
    """Read every jsonl file of the golden set."""
    cases: list[Case] = []
    for path in sorted(EVAL_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            it = raw["item"]
            item = Item(
                id=new_id(),
                student_id=new_id(),
                kind=raw["kind"],
                title=it["title"],
                organization=it.get("organization", ""),
                description=it.get("description", ""),
                grades=tuple(it.get("grades", ())),
                hours_per_week=it.get("hours_per_week"),
                weeks_per_year=it.get("weeks_per_year"),
            )
            item.validate()
            metrics = [
                Metric(
                    id=new_id(),
                    item_id=item.id,
                    label=m["label"],
                    value=Decimal(m["value"]),
                    unit=m.get("unit"),
                    horizon=m["horizon"],
                    target_date=(
                        date.fromisoformat(m["target_date"])
                        if m.get("target_date")
                        else None
                    ),
                )
                for m in raw["metrics"]
            ]
            words = ProfileWordsRef(tuple(raw["words"]), 1)
            expected = {d: (lo, hi) for d, (lo, hi) in raw["expected"].items()}
            cases.append(
                Case(
                    raw["id"], raw["locale"], ItemInput(item, metrics, words), expected
                )
            )
    return cases


def within_one(grade: str, band: tuple[str, str]) -> bool:
    """True when `grade` is at most one step outside the expected band."""
    lo, hi = sorted((POINTS[band[0]], POINTS[band[1]]))
    return lo - 1 <= POINTS[grade] <= hi + 1


def percentile(values: list[float], q: float) -> float:
    """Return the q-quantile (0..1) of the values, nearest rank."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))]


async def run(cases: list[Case], service: ItemReviewService, locale: str | None) -> int:
    """Review every case and print the metrics; return the exit code."""
    agree = total = valid = 0
    latencies: list[float] = []
    for case in cases:
        loc = locale or case.locale
        start = time.perf_counter()
        try:
            # `_ask` is the model step of `review` without storage or quota.
            review = await service._ask(case.data, "eval", loc)
        except AiInvalidOutputError:
            latencies.append(time.perf_counter() - start)
            print(f"{case.id}: invalid output")
            continue
        latencies.append(time.perf_counter() - start)
        valid += 1
        if review.safety_flag == "safeguarding":
            print(f"{case.id}: safeguarding")
            continue
        misses = []
        for dim in DIMENSIONS:
            total += 1
            got = review.grades[dim]
            if within_one(got, case.expected[dim]):
                agree += 1
            else:
                misses.append(f"{dim}={got} want {'-'.join(case.expected[dim])}")
        print(f"{case.id}: {review.overall} {'; '.join(misses) or 'ok'}")
    agreement = agree / total if total else 0.0
    validity = valid / len(cases) if cases else 0.0
    print(f"\ncases: {len(cases)}")
    print(f"agreement within ±1: {agreement:.1%}")
    print(f"schema validity: {validity:.1%}")
    if latencies:
        print(
            f"latency p50: {statistics.median(latencies):.2f}s, "
            f"p95: {percentile(latencies, 0.95):.2f}s"
        )
    ok = agreement >= THRESHOLD and validity >= THRESHOLD
    print("PASS" if ok else f"FAIL (threshold {THRESHOLD:.0%})")
    return 0 if ok else 1


async def _unbounded(user_id: object) -> int | None:
    return None


def main() -> int:
    """Parse arguments, check the gateway and run the evaluation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="example ids to run")
    parser.add_argument("--locale", choices=("uz", "ru", "en"), help="force a locale")
    args = parser.parse_args()
    settings = load_settings()
    key = settings.openrouter.api_key
    if settings.openrouter.mode != "real" or not (key and key.get_secret_value()):
        print("No OpenRouter key configured (mode real + API key): nothing to run.")
        return 0
    cases = load_cases()
    if args.only:
        cases = [c for c in cases if c.id in set(args.only)]
    ai = GatewayStructuredAi(NotebookLlm(make_llm_gateway(settings), settings))
    service = ItemReviewService(
        lambda: None,  # type: ignore[arg-type, return-value]
        None,  # type: ignore[arg-type]
        ai,
        SystemClock(),
        BuiltinPrompts(),
        per_day=_unbounded,
    )
    return asyncio.run(run(cases, service, args.locale))


if __name__ == "__main__":
    raise SystemExit(main())
