"""Shared pieces of the notebook tools: the late-bound API and source arguments."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.domain.errors import ToolFailedError
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi
from app.shared.contracts.notebooks import NotebooksCommands, NotebooksQueries

from pydantic import BaseModel, ConfigDict, Field

MAX_SOURCES = 20
TEXT_MAX_CHARS = 60_000
NOTEBOOK_URL = "/notebooks/view/?id={notebook_id}"
Title = Annotated[str, Field(min_length=1, max_length=255)]


class FileSourceArg(BaseModel):
    """One of the student's files as a source."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file"]
    file_id: UUID


class TextSourceArg(BaseModel):
    """Text the assistant writes or copies as a source."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["text"]
    title: Title
    text: str = Field(min_length=1, max_length=TEXT_MAX_CHARS)


SourceArg = FileSourceArg | TextSourceArg


def queries_of(bindings: LateBindings) -> NotebooksQueries:
    """Return the notebooks read API or fail like a tool."""
    if bindings.notebooks is None:
        raise ToolFailedError(support_details="notebooks are not available")
    return bindings.notebooks


def commands_of(bindings: LateBindings) -> NotebooksCommands:
    """Return the notebooks write API or fail like a tool."""
    if bindings.notebooks_commands is None:
        raise ToolFailedError(support_details="notebooks are not available")
    return bindings.notebooks_commands


async def check_files(files: FilesApi, sources: list[SourceArg], actor: Actor) -> None:
    """Every file source must be one of the student's own files."""
    for source in sources:
        if isinstance(source, FileSourceArg) and not await files.check_access(
            source.file_id, actor
        ):
            raise ToolFailedError(support_details=f"file {source.file_id} not found")


async def source_names(files: FilesApi, sources: list[SourceArg]) -> list[str]:
    """Return one line per source for an approval card: file names and text titles."""
    ids = [s.file_id for s in sources if isinstance(s, FileSourceArg)]
    refs = await files.get_many(ids) if ids else {}
    names: list[str] = []
    for source in sources:
        if isinstance(source, FileSourceArg):
            ref = refs.get(source.file_id)
            names.append(ref.name if ref is not None else str(source.file_id))
        else:
            names.append(source.title)
    return names


def source_dicts(sources: list[SourceArg]) -> list[dict[str, Any]]:
    """Return the sources as plain dicts for `NotebooksCommands`."""
    return [s.model_dump(mode="json") for s in sources]


async def notebook_title(
    bindings: LateBindings, user_id: UUID, notebook_id: UUID
) -> str:
    """Return the title of the student's notebook or fail."""
    found = await queries_of(bindings).get_notebook(user_id, notebook_id)
    if found is None:
        raise ToolFailedError(support_details="notebook not found")
    return str(found.get("title", ""))
