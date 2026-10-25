"""Budget estimate of a whole plan-then-generate run (a soft pre-check)."""

import math
from dataclasses import dataclass
from typing import Final

from app.modules.notebooks.domain.assessment.blueprint import plan_tokens
from app.modules.notebooks.domain.assessment.items import VERIFY_MAX_TOKENS
from app.modules.notebooks.domain.assessment.profile import (
    PROFILE_MAX_TOKENS,
    SAMPLE_CHARS,
)
from app.modules.notebooks.domain.tokens import OUTPUT_WEIGHT, estimate_tokens

ITEM_MAX_TOKENS: Final = 750  # answer budget per item of a batch
BATCH_MAX_ITEMS: Final = 25  # keeps one call under ~19k output tokens
BATCH_EXTRA_TOKENS: Final = 300  # the title and the JSON frame of a batch
VERIFY_ITEM_TOKENS: Final = 250  # one item as the solver reads it
REFILL_SHARE: Final = 0.25  # expected share of slots written again


@dataclass(frozen=True, slots=True)
class PipelineShape:
    """What decides the number and size of the calls."""

    count: int
    batch_size: int
    fill_rounds: int
    verify: bool


def batch_tokens(items: int) -> int:
    """`max_tokens` of a batch of `items` slots."""
    return ITEM_MAX_TOKENS * items + BATCH_EXTRA_TOKENS


def pipeline_estimate(input_tokens: int, sources: int, shape: PipelineShape) -> int:
    """Weighted tokens of profile + plan + batches x (write + verify) + refills."""
    size = max(1, min(shape.batch_size, BATCH_MAX_ITEMS))
    count = max(1, shape.count)
    batches = math.ceil(count / size)
    profile_in = min(input_tokens, estimate_tokens(SAMPLE_CHARS * max(1, sources)))
    fixed = (
        profile_in
        + PROFILE_MAX_TOKENS * OUTPUT_WEIGHT
        + input_tokens
        + plan_tokens(count) * OUTPUT_WEIGHT
    )
    writes = batches * input_tokens + count * ITEM_MAX_TOKENS * OUTPUT_WEIGHT
    writes += batches * BATCH_EXTRA_TOKENS * OUTPUT_WEIGHT
    checks = (
        batches * VERIFY_MAX_TOKENS * OUTPUT_WEIGHT + count * VERIFY_ITEM_TOKENS
        if shape.verify
        else 0
    )
    refill = math.ceil((writes + checks) * REFILL_SHARE) if shape.fill_rounds else 0
    return fixed + writes + checks + refill
