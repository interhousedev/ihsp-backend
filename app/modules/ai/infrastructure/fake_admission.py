"""Deterministic fake documents for the admission item review and interview."""

from typing import Any

REVIEW_SCHEMA = "admission_item_review"
INTERVIEW_SCHEMA = "admission_item_interview"
REWRITE_SCHEMA = "admission_item_rewrite"
FINAL_ROUND_MARK = "This is the end of the interview"

_DIMENSIONS = ("clarity", "role_name", "impact", "alignment")
_REWRITE: dict[str, Any] = {
    "position": "Club founder",
    "org": "School robotics club",
    "description": "Founded and led a weekly robotics club for younger students.",
    "claim_refs": [],
}


def build_admission_document(schema_name: str, system: str) -> dict[str, Any] | None:
    """Return a schema-valid document for an admission item schema, else None."""
    if schema_name == REVIEW_SCHEMA:
        return {
            "dimensions": [
                {
                    "dim": dim,
                    "evidence": f"Sample evidence for {dim}.",
                    "grade": "B",
                    "suggestion": f"Add one concrete fact about {dim}.",
                }
                for dim in _DIMENSIONS
            ],
            "word_fit": [],
            "rewrite": dict(_REWRITE),
            "missing_facts": ["How many students took part?"],
            "injection_suspected": False,
            "safeguarding": False,
        }
    if schema_name == REWRITE_SCHEMA:
        return dict(_REWRITE)
    if schema_name == INTERVIEW_SCHEMA:
        final = FINAL_ROUND_MARK in system
        questions = [
            {
                "gap": "numbers",
                "question": "How many people took part?",
                "why_it_matters": "Numbers show the scale of your impact.",
                "options": ["Under 10", "10 to 50", "Over 50"],
            },
            {
                "gap": "role",
                "question": "What exactly was your role?",
                "why_it_matters": "Readers look for what you did yourself.",
                "options": [],
            },
        ]
        return {
            "questions": [] if final else questions,
            "ready_for_review": final,
            "proposal": dict(_REWRITE),
            "injection_suspected": False,
            "safeguarding": False,
        }
    return None
