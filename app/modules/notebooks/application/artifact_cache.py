"""Sharing finished Studio outputs between students who ask for the same thing."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.artifacts.cache_key import artifact_cache_key
from app.modules.notebooks.domain.entities import (
    Artifact,
    CachedArtifact,
    Notebook,
    Source,
)
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.shared.ids import new_id


def key_for_request(
    *,
    kind: ArtifactKind,
    report_format: str | None,
    options: Mapping[str, Any],
    prompt: str | None,
    sources: Sequence[Source],
    language: str,
) -> str | None:
    """The cache key of a request; None when it must be generated for this student.

    A custom focus text is the student's own question, and a source without a shared
    document (an old row) cannot be matched. Course plans and lesson drafts depend on
    the draft of one course and are never shared.
    """
    if prompt or kind.is_course_kind:
        return None
    if any(s.content_hash is None or s.document_id is None for s in sources):
        return None
    return artifact_cache_key(
        kind=kind.value,
        report_format=report_format,
        options=options,
        content_hashes=[s.content_hash for s in sources if s.content_hash],
        language=language,
    )


def served_from_cache(
    *,
    entry: CachedArtifact,
    notebook: Notebook,
    sources: Sequence[Source],
    options: dict[str, Any],
    now: datetime,
) -> Artifact | None:
    """A `ready` output for the student from a cached one; None if it does not fit.

    The cited passages are shared (they belong to the documents), so only the
    source ids and titles are pointed at the student's own sources.
    """
    own = {str(s.document_id): s for s in sources}
    mapping: dict[str, Source] = {}
    for generator_source, document in entry.source_documents.items():
        if document not in own:
            return None
        mapping[generator_source] = own[document]
    source_map = {}
    for label, generator_source in entry.source_map.items():
        if generator_source not in mapping:
            return None
        source_map[label] = str(mapping[generator_source].id)
    return Artifact(
        id=new_id(),
        notebook_id=notebook.id,
        owner_id=notebook.owner_id,
        kind=entry.kind,
        title=entry.title[:ARTIFACT_TITLE_MAX_CHARS],
        created_at=now,
        updated_at=now,
        status=ArtifactStatus.READY,
        format=entry.format,
        options=options,
        source_ids=[s.id for s in sources],
        source_map=source_map,
        sampled=entry.sampled,
        content=entry.content,
        refs_index=_own_refs(entry.refs_index, mapping),
        model=entry.model,
        started_at=now,
        finished_at=now,
        cache_key=entry.cache_key,
        from_cache=True,
    )


def _own_refs(
    refs_index: dict[str, Any] | None, mapping: Mapping[str, Source]
) -> dict[str, Any] | None:
    """The reference index with each cited source replaced by the student's own."""
    if refs_index is None:
        return None
    own: dict[str, Any] = {}
    for label, ref in refs_index.items():
        source = mapping.get(str(ref.get("source_id")))
        own[label] = (
            ref
            if source is None
            else {**ref, "source_id": str(source.id), "source_title": source.title}
        )
    return own


def shared_entry(
    *,
    artifact: Artifact,
    title: str,
    content: dict[str, Any],
    refs_index: dict[str, Any] | None,
    source_map: Mapping[str, str],
    sources: Sequence[Source],
    sampled: bool,
    model: str | None,
) -> CachedArtifact | None:
    """What to keep of a generated output; None when the cache key is missing."""
    if artifact.cache_key is None:
        return None
    documents: dict[str, str] = {}
    for source in sources:
        if source.document_id is None:
            return None
        documents[str(source.id)] = str(source.document_id)
    wanted = {UUID(v) for v in source_map.values()}
    return CachedArtifact(
        cache_key=artifact.cache_key,
        kind=artifact.kind,
        title=title,
        format=artifact.format,
        content=content,
        refs_index=refs_index,
        source_map=dict(source_map),
        source_documents={k: v for k, v in documents.items() if UUID(k) in wanted},
        options=artifact.options,
        sampled=sampled,
        model=model,
    )
