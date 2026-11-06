"""Students tool `list_files`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.shared.actor import Actor
from app.shared.contracts.files import FileRef
from app.shared.contracts.mcp_files_courses import FileOrigin

from pydantic import Field

SCOPE = "files:read"
WIDE_SCOPE = "files:read.all"
FLASHCARDS_SCOPE = "flashcards:read"
_SET_FIELDS = ("id", "title", "description", "source", "card_count")
_UNTRUSTED = ("files[].name", "flashcard_sets[].title", "flashcard_sets[].description")


def _row(file: FileRef, open_url: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "file_id": file.id,
        "name": file.name,
        "content_type": file.content_type,
        "byte_size": file.byte_size,
        "has_text": file.text_bytes is not None,
        "text_bytes": file.text_bytes,
        "links": {"open": open_url},
        **extra,
    }


def _summary(result: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "count": len(result.get("files", [])),
        "sets": len(result.get("flashcard_sets", [])),
    }


async def _flashcard_sets(kit: ToolKit, actor: Actor, limit: int) -> dict[str, Any]:
    """The actor's sets as entries; a shared set arrives as the actor's own copy."""
    if not await kit.guard.has_scope(actor, FLASHCARDS_SCOPE):
        return {"flashcard_sets": [], "flashcard_sets_scope_limited": True}
    sets = await kit.deps.flashcards.list_sets(actor.user_id)
    return {
        "flashcard_sets": [
            {
                **{name: row.get(name) for name in _SET_FIELDS},
                "kind": "shared" if row.get("source") == "copied" else "personal",
                "links": kit.deps.web_links.flashcard_set(UUID(str(row["id"]))),
            }
            for row in sets[:limit]
        ],
        "flashcard_sets_scope_limited": False,
    }


def register(kit: ToolKit) -> None:
    """Register `list_files`."""

    @kit.tool(
        SCOPE,
        log=LogSpec(
            keep=("limit", "only_personal", "origin", "subject_id"),
            summarize=_summary,
        ),
    )
    async def list_files(
        limit: Annotated[int, Field(ge=1, le=100, description="Most files.")] = 50,
        only_personal: Annotated[
            bool, Field(description="Search only personal uploaded files.")
        ] = False,
        origin: Annotated[
            FileOrigin | None, Field(description="Only files of this origin.")
        ] = None,
        subject_id: Annotated[
            UUID | None, Field(description="Only files of this subject's lessons.")
        ] = None,
    ) -> dict[str, Any]:
        """List files the student may read, newest first.

        By default: own uploads, files shared with the student, files of all subjects
        and lessons, of notebooks (subject, LMS and custom) and of flash card sets.
        This needs `files:read.all`; otherwise, or with only_personal, only own uploads
        come back (`scope_limited` tells when the scope was the reason).
        `has_text` tells whether read_file can return the file's text.
        With origin `flashcards`, `flashcard_sets` also lists the student's own sets
        with links (`kind`: personal, or shared for a copy of someone's set); this needs
        `flashcards:read`. `files` then holds only the source files of those sets.
        """
        actor = current_actor()
        deps = kit.deps
        open_url = deps.web_links.files()["open"]
        wide = await kit.guard.has_scope(actor, WIDE_SCOPE)
        sets = (
            await _flashcard_sets(kit, actor, limit)
            if origin == "flashcards" and not only_personal
            else {}
        )
        if only_personal or not wide:
            owned = await deps.files.list_owned(actor.user_id, limit=limit)
            rows = [_row(item, open_url, origin="personal") for item in owned]
            return mark_untrusted(
                {
                    "files": rows,
                    "scope_limited": not only_personal and not wide,
                    **sets,
                },
                *_UNTRUSTED,
            )
        visible = await deps.files_courses_tools.visible_files(
            actor,
            only_personal=False,
            origin=origin,
            subject_id=subject_id,
            limit=limit,
        )
        refs = await deps.files.get_many([item.file_id for item in visible])
        rows = [
            _row(
                refs[item.file_id],
                open_url,
                origin=item.origin,
                origin_id=item.origin_id,
                subject_id=item.subject_id,
                origin_detail=item.detail,
            )
            for item in visible
            if item.file_id in refs
        ]
        return mark_untrusted(
            {"files": rows, "scope_limited": False, **sets}, *_UNTRUSTED
        )
