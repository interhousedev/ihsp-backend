"""The catalogue of declared AI requests against the real prompt slots."""

from app.bootstrap.adapters.prompt_slots import prompt_slots
from app.modules.ai.application.request_catalog import declared_requests
from app.modules.ai.domain.args_schema import validate_args
from app.modules.ai.domain.requests import build_catalog


def test_declared_requests_have_unique_ids_and_known_slots() -> None:
    """Every declared request renders a slot the registry knows."""
    declared = declared_requests()
    slots = {slot.key for slot in prompt_slots()}

    assert len({spec.id for spec in declared}) == len(declared)
    for spec in declared:
        assert (spec.template.task, spec.template.name) in slots, spec.id
        assert spec.pipeline


def test_every_template_placeholder_is_a_required_argument() -> None:
    """A template request must declare each placeholder its template fills."""
    for spec in declared_requests():
        required = set(spec.args_schema.get("required", ()))
        assert set(spec.template.fields) <= required, spec.id


def test_reference_call_sites_are_declared() -> None:
    """Chat and studio quiz are converted: their requests exist."""
    ids = {spec.id for spec in declared_requests()}

    assert {
        "ai.student_chat.turn",
        "ai.student_chat_smart.turn",
        "ai.admin_chat.turn",
        "notebooks.studio_quiz.generate",
    } <= ids
    quiz = next(s for s in declared_requests() if s.id.endswith("studio_quiz.generate"))
    assert validate_args(quiz.args_schema, {"language": "Uzbek", "count": 5}) == []


def test_catalog_adds_an_auto_spec_for_each_remaining_slot() -> None:
    """Slots no declared request renders still get one `ai.<task>.<name>`."""
    catalog = build_catalog(prompt_slots(), declared_requests())
    ids = {spec.id for spec in catalog}

    assert len(ids) == len(catalog)
    assert "ai.student_chat.data_rules" in ids
    assert len(catalog) >= len(prompt_slots()) - 3
