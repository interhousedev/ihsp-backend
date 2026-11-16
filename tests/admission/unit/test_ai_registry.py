"""Admission prompts resolve through the registry; fake model fills schemas."""

from app.bootstrap.adapters.prompt_slots import _PARTS  # noqa: F401
from app.modules.admin.domain.limits import group_of
from app.modules.admission.infrastructure.ai.prompt_source import BUILTIN_PROMPTS
from app.modules.admission.infrastructure.ai.prompts.alignment_map import (
    AlignmentMap,
)
from app.modules.ai.infrastructure.fake_schema import document_for


def test_limit_group() -> None:
    assert group_of("admit_item_review_per_day") == "admission"


def test_builtins_cover_every_task_name() -> None:
    assert ("admit_item_review", "system") in BUILTIN_PROMPTS
    assert all(text.strip() for text in BUILTIN_PROMPTS.values())


def test_fake_document_validates() -> None:
    schema = AlignmentMap.model_json_schema()
    AlignmentMap.model_validate(document_for(schema))
