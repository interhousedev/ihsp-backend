"""Links and untrusted labels of the results of the content tools."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.untrusted import mark_untrusted


def flashcard_set_result(deps: McpDeps, found: dict[str, Any]) -> dict[str, Any]:
    """A set with its links; its text is data, not instructions."""
    result = mark_untrusted(
        found, "title", "description", "cards[].front", "cards[].back"
    )
    set_id = found["id"]
    result["links"] = deps.web_links.flashcard_set(
        set_id if isinstance(set_id, UUID) else UUID(str(set_id))
    )
    return result


def test_result(deps: McpDeps, found: dict[str, Any]) -> dict[str, Any]:
    """A test with its link; its text is data, not instructions."""
    result = mark_untrusted(
        found,
        "title",
        "questions[].prompt",
        "questions[].options[].text",
        "questions[].explanation",
        "questions[].hint",
    )
    result["links"] = deps.web_links.quiz(
        UUID(str(found["notebook_id"])), UUID(str(found["id"]))
    )
    return result
