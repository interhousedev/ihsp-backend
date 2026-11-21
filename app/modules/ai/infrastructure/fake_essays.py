"""Deterministic fake documents for the admission essay reviews and reads."""

import re
from collections.abc import Sequence
from typing import Any

from app.modules.ai.infrastructure.fake_sources import last_user_text

_DIMS = ("responsiveness", "hook", "detail", "voice", "reflection", "writing")
_PARAGRAPH = re.compile(r"^\[(\d+)\]\s*(.+)$", re.MULTILINE)
_GOAL = re.compile(r"\[goal key=([^\]]+)\]")
_ESSAY = re.compile(r"^Essay:\s*(\S.*)$", re.MULTILINE)
_ROLES = ("hook", "context", "turn", "evidence", "insight", "close")


def _quote(text: str) -> str:
    """The first words of a line: a verbatim quote of the essay."""
    return " ".join(text.split()[:6])


def _essay_line(text: str) -> str:
    found = _ESSAY.search(text)
    return found.group(1) if found else ""


def build_essay_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a valid, non-degenerate document for an essay schema, else None."""
    text = last_user_text(messages)
    if schema_name == "essay_base_review":
        quote = _quote(_essay_line(text))
        return {
            "dimensions": [
                {
                    "dim": dim,
                    "score": 3,
                    "quote": quote,
                    "comment": f"Sample note on {dim}.",
                }
                for dim in _DIMS
            ],
            "summary": "A clear essay with a personal angle; add more detail.",
            "strengths": ["A distinct personal angle."],
            "improvements": ["Show one more concrete scene."],
            "paragraphs": [{"paragraph": 1, "note": "Sets up the idea well."}],
            "patterns": [],
        }
    if schema_name == "essay_uni_review":
        quote = _quote(_essay_line(text))
        keys = _GOAL.findall(text)
        return {
            "alignment": 62,
            "goals": [
                {
                    "key": key,
                    "alignment": ("strong", "partial", "missing")[n % 3],
                    "evidence": "" if n % 3 == 2 else quote,
                    "suggestion": "Show this value through one more example.",
                }
                for n, key in enumerate(keys)
            ],
            "fit_summary": "The essay fits this university's values in part.",
            "supplement_tips": ["Tie the essay to a specific program."],
            "risks": ["The tone may read as abstract."],
        }
    if schema_name == "essay_deep_read":
        paragraphs = [(int(n), t) for n, t in _PARAGRAPH.findall(text)] or [(1, "")]
        return {
            "paragraphs": [
                {
                    "paragraph": n,
                    "role": _ROLES[i % len(_ROLES)],
                    "reveals": "Curiosity and a habit of testing ideas.",
                    "strength": "strong" if i == 0 else "ok",
                }
                for i, (n, _) in enumerate(paragraphs)
            ],
            "uniqueness": 68,
            "uniqueness_note": "A recognisable voice with a few stock moves.",
            "tropes": ["The big question"],
            "moments": (
                [{"paragraph": n, "quote": _quote(t), "kind": "fresh"}]
                if (n := paragraphs[0][0]) and (t := paragraphs[0][1])
                else []
            ),
            "fix_paragraph": paragraphs[-1][0],
            "fix_dimension": "detail",
            "fix_problem": "The ending stays general.",
            "fix_try": "Name one concrete moment that changed your mind.",
        }
    if schema_name == "essay_practice":
        return {
            "summary": "A lively entry with a clear turn.",
            "scores": [
                {"key": key, "score": 3, "comment": f"Sample note on {key}."}
                for key in ("imagery", "voice", "structure", "originality")
            ],
            "praise": ["A distinct voice."],
            "try_next": ["Add one sensory detail."],
            "idea_seeds": ["The first moment the idea clicked"],
        }
    return None
