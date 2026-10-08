"""LMS-23, MCP-6: IDs, file references and add-only edits of step content."""

from uuid import UUID

from app.modules.lms.domain.authoring.content_edit import (
    collect_ids,
    extract_file_ids,
    with_block_appended,
    with_question_appended,
)
from app.modules.lms.domain.authoring.errors import ContentInvalidError

import pytest

FILE_A = "0192f3c4-aaaa-7bbb-8ccc-0123456789ab"
FILE_B = "0192f3c5-aaaa-7bbb-8ccc-0123456789ab"

CONTENT = {
    "title": "Rules",
    "blocks": [
        {
            "id": "b1",
            "type": "text",
            "markdown": f"![x](/files/{FILE_A}) and /files/{FILE_A}",
        },
        {
            "id": "b2",
            "type": "test",
            "config": {},
            "questions": [
                {
                    "id": "q1",
                    "type": "single",
                    "prompt": f"See /files/{FILE_B}",
                    "options": [{"id": "o1", "text": "2x"}, {"id": "o2", "text": "x"}],
                }
            ],
        },
        {
            "id": "b3",
            "type": "flashcards",
            "cards": [{"id": "c1", "front": "f", "back": "b"}],
        },
    ],
}


def test_every_id_at_every_depth_is_collected() -> None:
    """Blocks, questions, options and cards all carry IDs."""
    assert collect_ids(CONTENT) == {"b1", "b2", "q1", "o1", "o2", "b3", "c1"}


def test_empty_ids_are_not_ids() -> None:
    """New elements arrive without an ID."""
    assert (
        collect_ids({"blocks": [{"id": "", "type": "text"}, {"type": "text"}]}) == set()
    )


def test_file_references_are_found_in_any_text_once() -> None:
    """Files used in Markdown, prompts and so on are tracked (README: file_ids)."""
    assert extract_file_ids(CONTENT) == [UUID(FILE_A), UUID(FILE_B)]


def test_content_without_files_has_no_file_ids() -> None:
    """A normal link is not a file reference."""
    assert (
        extract_file_ids({"title": "x", "blocks": [{"markdown": "https://a.b/files"}]})
        == []
    )


def test_block_is_appended_to_a_copy() -> None:
    """MCP additions never change the content they start from."""
    block = {"type": "text", "markdown": "New"}

    result = with_block_appended(CONTENT, block)

    assert len(CONTENT["blocks"]) == 3
    assert result["blocks"][-1] == block


def test_question_is_appended_to_a_test_block_only() -> None:
    """MCP can add questions to tests, not to text blocks or unknown blocks."""
    question = {"type": "number", "prompt": "2+2", "answer": {"value": 4}}

    result = with_question_appended(CONTENT, "b2", question)

    assert result["blocks"][1]["questions"][-1] == question
    assert len(CONTENT["blocks"][1]["questions"]) == 1
    with pytest.raises(ContentInvalidError):
        with_question_appended(CONTENT, "b1", question)
    with pytest.raises(ContentInvalidError):
        with_question_appended(CONTENT, "missing", question)
