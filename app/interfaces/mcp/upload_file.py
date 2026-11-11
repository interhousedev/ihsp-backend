"""`upload_file`: a ChatGPT file parameter or base64 content becomes a ready file.

Registered on the student and teacher servers. The file is owned by the caller and
counts against the caller's file quota; it shows up in the Files list like any
upload. The download URL of a file parameter is untrusted: see upload_fetch.py.
"""

import asyncio
import base64
from typing import Annotated, Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import (
    McpInvalidInputError,
    McpUploadNotReadyError,
    McpUploadTooLargeError,
)
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.upload_fetch import SafeUploadFetcher, parse_hosts
from app.shared.actor import Role
from app.shared.contracts.files import FilePurpose, FileScope

from pydantic import BaseModel, Field

SCOPE = "files:write"
MAX_BASE64_BYTES = 5 * 1024 * 1024  # decoded size of content_base64
READY_TIMEOUT = 30.0
POLL_INTERVAL = 1.0
REFUSED = frozenset({"rejected", "deleted"})

_BASE_DOC = """Upload a file and get its file_id.

Pass `file` (the file the user attached in the chat) or `content_base64` with
`name` (up to 5 MiB). Returns `file_id`, `name`, `size` and `content_type` of a ready
file in the user's own Files list. Nothing is submitted or shared by this call."""
_DOC_BY_SERVER = {
    "student": _BASE_DOC
    + " To hand it in, follow with `submit_homework` and pass the `file_id`.",
    "teacher": _BASE_DOC
    + " Attach it to a lesson or homework with the tools that take `file_id`.",
}


class ChatGptFile(BaseModel):
    """What ChatGPT sends for a file parameter."""

    download_url: str
    file_id: str
    mime_type: str | None = None
    file_name: str | None = None


def _scope_for(actor_is_student: bool) -> FileScope:
    return FileScope.STUDENT if actor_is_student else FileScope.STAFF


def decode_base64(content: str, name: str | None) -> tuple[str, bytes]:
    """Check `content_base64` and its name; return (name, bytes)."""
    if not name or not name.strip():
        raise McpInvalidInputError(
            params={"reason": "name is required with content_base64"}
        )
    if len(content) > (MAX_BASE64_BYTES // 3 + 1) * 4:
        raise McpUploadTooLargeError(params={"max_bytes": MAX_BASE64_BYTES})
    try:
        data = base64.b64decode(content, validate=True)
    except ValueError as exc:
        raise McpInvalidInputError(
            params={"reason": "content_base64 is not valid base64"}
        ) from exc
    if len(data) > MAX_BASE64_BYTES:
        raise McpUploadTooLargeError(params={"max_bytes": MAX_BASE64_BYTES})
    if not data:
        raise McpInvalidInputError(params={"reason": "the file is empty"})
    return name.strip(), data


async def _wait_ready(kit: ToolKit, file_id: Any) -> Any:  # noqa: ANN401
    loop = asyncio.get_running_loop()
    deadline = loop.time() + READY_TIMEOUT
    while True:
        ref = await kit.deps.files.get(file_id)
        status = None if ref is None else str(getattr(ref.status, "value", ref.status))
        if ref is not None and status == "ready":
            return ref
        if status is None or status in REFUSED or loop.time() >= deadline:
            raise McpUploadNotReadyError()
        await asyncio.sleep(POLL_INTERVAL)


def register(kit: ToolKit) -> None:
    """Register `upload_file` on a server."""

    async def upload_file(
        file: Annotated[
            ChatGptFile | None,
            Field(description="A file the user attached in the chat."),
        ] = None,
        name: Annotated[
            str | None,
            Field(description="File name with extension. Required for base64."),
        ] = None,
        content_base64: Annotated[
            str | None,
            Field(description="The file bytes in base64 (up to 5 MiB decoded)."),
        ] = None,
    ) -> dict[str, Any]:
        actor = current_actor()
        if (file is None) == (content_base64 is None):
            raise McpInvalidInputError(
                params={"reason": "pass exactly one of file and content_base64"}
            )
        if file is not None:
            settings = kit.deps.settings
            fetcher = SafeUploadFetcher(
                allowed_hosts=parse_hosts(settings.mcp.upload_hosts),
                max_bytes=settings.limits.file_max_bytes,
            )
            downloaded = await fetcher.fetch(file.download_url)
            stored_name = (name or file.file_name or "").strip() or downloaded.name
            data = downloaded.data
        else:
            assert content_base64 is not None
            stored_name, data = decode_base64(content_base64, name)
        stored = await kit.deps.files.store_bytes(
            owner_id=actor.user_id,
            scope=_scope_for(actor.has(Role.STUDENT)),
            purpose=FilePurpose.AI_UPLOAD,
            name=stored_name,
            data=data,
        )
        ref = await _wait_ready(kit, stored.id)
        return {
            "file_id": str(ref.id),
            "name": ref.name,
            "size": ref.byte_size,
            "content_type": ref.content_type,
        }

    upload_file.__doc__ = _DOC_BY_SERVER.get(kit.guard.server, _BASE_DOC)
    kit.tool(
        SCOPE,
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(),
        meta={"openai/fileParams": ["file"]},
    )(upload_file)
