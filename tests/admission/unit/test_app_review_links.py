"""Link validation of the application review and the v1 stored shape."""

from app.interfaces.http.v1.admission.routes_app_review import ReviewSectionOut
from app.modules.admission.application.app_review import clean_link, section_view
from app.modules.admission.infrastructure.ai.prompt_source import BUILTIN_PROMPTS
from app.modules.admission.infrastructure.ai.prompts import app_review as prompt
from app.shared.ai_tasks import AiTask

KNOWN = frozenset({"essay:e1", "item:i1", "entry:n1", "answer:q20"})


def test_clean_link_keeps_known_refs_and_drops_invented() -> None:
    assert clean_link("essay", "e1", KNOWN) == {"kind": "essay", "ref": "e1"}
    assert clean_link("list_entry", "n1", KNOWN)["ref"] == "n1"
    assert clean_link("honors", "i1", KNOWN)["ref"] == "i1"
    assert clean_link("survey", "q20", KNOWN)["ref"] == "q20"
    assert clean_link("essay", "nope", KNOWN) == {"kind": "none", "ref": ""}
    assert clean_link("essay", "i1", KNOWN) == {"kind": "none", "ref": ""}
    assert clean_link("tests", "x", KNOWN) == {"kind": "none", "ref": ""}
    assert clean_link("bogus", "", KNOWN) == {"kind": "none", "ref": ""}
    assert clean_link("tests", "", KNOWN) == {"kind": "tests", "ref": ""}
    assert clean_link("essay", "", KNOWN) == {"kind": "essay", "ref": ""}


def test_section_view_cleans_links_and_finding_indexes() -> None:
    out = prompt.SectionReport.model_validate(
        {
            "score": 6,
            "summary": "s",
            "ao_view": "A reader may notice focus.",
            "subsections": [
                {
                    "key": "essay:e1",
                    "title": "Main essay",
                    "verdict": "mixed",
                    "ao_view": "v",
                    "finding_indexes": [1, 5, 0],
                    "link": {"kind": "essay", "ref": "e1"},
                }
            ],
            "findings": [
                {
                    "kind": "gap",
                    "text": " ",
                    "evidence": [],
                    "link": {"kind": "none", "ref": ""},
                },
                {
                    "kind": "risk",
                    "text": "Vague",
                    "evidence": ["essay:e1"],
                    "link": {"kind": "essay", "ref": "ghost"},
                },
            ],
            "next_actions": [],
            "injection_suspected": False,
        }
    )
    view = section_view(out, KNOWN)
    assert view["findings"][0]["link"] == {"kind": "none", "ref": ""}
    assert len(view["findings"]) == 1
    assert view["subsections"][0]["finding_indexes"] == [0]
    assert view["subsections"][0]["link"]["ref"] == "e1"


def test_v1_stored_section_still_parses() -> None:
    v1 = {
        "key": "essays",
        "status": "done",
        "score": 5,
        "summary": "x",
        "findings": [{"kind": "gap", "text": "t", "evidence": []}],
        "next_actions": [],
    }
    out = ReviewSectionOut.model_validate(v1)
    assert out.ao_view == ""
    assert out.subsections == []
    assert out.findings[0].link.kind == "none"


def test_schema_has_no_nullables_and_rules_slot_is_builtin() -> None:
    assert "null" not in str(prompt.SECTION_SCHEMA)
    assert prompt.PROMPT_VERSION == "app_review@2"
    assert (
        BUILTIN_PROMPTS[(AiTask.ADMIT_APP_REVIEW_LEAD.value, "rules")] == prompt.RULES
    )
    assert "Hoffman" not in prompt.RULES
