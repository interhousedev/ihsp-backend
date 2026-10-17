"""Helpers over step content JSON: IDs, file references, add-only edits."""

import copy
import json
import re
from typing import Any, Final
from uuid import UUID

from app.modules.lms.domain.authoring.errors import ContentInvalidError

FILE_REFERENCE: Final = re.compile(
    r"/files/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12})"
)


def collect_ids(value: Any) -> set[str]:  # noqa: ANN401 - any JSON value
    """Collect every non-empty string under an `id` key, at any depth."""
    found: set[str] = set()
    if isinstance(value, dict):
        item_id = value.get("id")
        if isinstance(item_id, str) and item_id:
            found.add(item_id)
        for child in value.values():
            found |= collect_ids(child)
    elif isinstance(value, list):
        for child in value:
            found |= collect_ids(child)
    return found


def strip_empty_ids(value: Any) -> Any:  # noqa: ANN401 - any JSON value
    """Return a copy without `id` keys that are empty strings or null.

    Clients (MCP tools, the editor) send `""` for new blocks, questions, options
    and cards; that must mean exactly the same as a missing ID.
    """
    if isinstance(value, dict):
        return {
            key: strip_empty_ids(child)
            for key, child in value.items()
            if not (key == "id" and child in ("", None))
        }
    if isinstance(value, list):
        return [strip_empty_ids(child) for child in value]
    return value


def extract_file_ids(content: dict[str, Any]) -> list[UUID]:
    """Return the IDs of files referenced as `/files/{uuid}` anywhere in the content."""
    text = json.dumps(content, ensure_ascii=False)
    found = {UUID(match) for match in FILE_REFERENCE.findall(text)}
    return sorted(found | set(video_file_ids(content)))


VIDEO_TYPES = ("video", "interactive_video")


def video_file_ids(content: dict[str, Any]) -> list[UUID]:
    """Return the IDs of the files of uploaded video blocks."""
    ids: list[UUID] = []
    for block in content.get("blocks", []):
        if block.get("type") in VIDEO_TYPES and block.get("source") == "upload":
            try:
                ids.append(UUID(str(block.get("file_id"))))
            except ValueError:
                continue
    return ids


def with_block_appended(
    content: dict[str, Any], block: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of the content with the block added at the end."""
    result = copy.deepcopy(content)
    result.setdefault("blocks", []).append(strip_empty_ids(block))
    return result


def with_question_appended(
    content: dict[str, Any], block_id: str, question: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of the content with a question added to a test block."""
    result = copy.deepcopy(content)
    for block in result.get("blocks", []):
        if block.get("id") == block_id:
            if block.get("type") != "test":
                raise ContentInvalidError(
                    params={"reason": "not-a-test-block", "block_id": block_id}
                )
            block.setdefault("questions", []).append(strip_empty_ids(question))
            return result
    raise ContentInvalidError(
        params={"reason": "block-not-found", "block_id": block_id}
    )
