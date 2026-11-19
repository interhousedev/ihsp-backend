"""Exemplar essay library: counselor curation and student excerpts."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.modules.admission.application.exemplars import (
    ExemplarInput,
    ExemplarPublic,
)
from app.modules.admission.domain.exemplars import (
    MAX_BODY_LEN,
    MAX_IMPORT,
    MAX_PROMPT_LEN,
    MAX_TAGS,
    MAX_TITLE_LEN,
    MAX_URL_LEN,
    Exemplar,
)

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Kind = Literal["personal_statement", "supplement", "why_us", "activity", "other"]
Status = Literal["draft", "published", "archived"]


class ProblemOut(BaseModel):
    """problem+json body of a refused request."""

    type: str
    title: str
    status: int
    message_key: str
    params: dict[str, Any]


class ExemplarIn(BaseModel):
    """A new exemplar; a catalog token always gets a draft."""

    kind: Kind
    title: str = Field(max_length=MAX_TITLE_LEN + 200)
    body: str = Field(max_length=MAX_BODY_LEN * 2)
    source_url: str = Field(max_length=MAX_URL_LEN * 2)
    institution_id: UUID | None = None
    school_name: str = Field(default="", max_length=1000)
    year: int | None = None
    prompt: str = Field(default="", max_length=MAX_PROMPT_LEN * 2)
    source_name: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS * 4)
    notes: str = Field(default="", max_length=20000)
    language: str = Field(default="en", max_length=16)
    status: Status = "draft"

    def to_input(self) -> ExemplarInput:
        """The application input."""
        return ExemplarInput(**self.model_dump())


class ExemplarImportIn(BaseModel):
    """Up to 50 exemplars; all are stored as drafts."""

    items: list[ExemplarIn] = Field(max_length=MAX_IMPORT * 4)


class ExemplarPatchIn(BaseModel):
    """Changed fields only, with the lock of the version they were read at."""

    lock_version: int
    kind: Kind | None = None
    title: str | None = Field(default=None, max_length=MAX_TITLE_LEN + 200)
    body: str | None = Field(default=None, max_length=MAX_BODY_LEN * 2)
    source_url: str | None = Field(default=None, max_length=MAX_URL_LEN * 2)
    institution_id: UUID | None = None
    school_name: str | None = Field(default=None, max_length=1000)
    year: int | None = None
    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_LEN * 2)
    source_name: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS * 4)
    notes: str | None = Field(default=None, max_length=20000)
    language: str | None = Field(default=None, max_length=16)
    status: Status | None = None

    def changes(self) -> dict[str, Any]:
        """The fields the caller sent (null clears institution and year only)."""
        sent = self.model_dump(exclude_unset=True, exclude={"lock_version"})
        nullable = {"institution_id", "year"}
        return {k: v for k, v in sent.items() if v is not None or k in nullable}


class ExemplarOut(BaseModel):
    """An exemplar with its body, for curators."""

    id: UUID
    institution_id: UUID | None
    school_name: str
    year: int | None
    kind: Kind
    prompt: str
    title: str
    body: str
    word_count: int
    source_url: str
    source_name: str
    tags: list[str]
    notes: str
    status: Status
    language: str
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    lock_version: int

    @classmethod
    def of(cls, e: Exemplar) -> "ExemplarOut":
        """Map the domain value."""
        return cls(
            id=e.id,
            institution_id=e.institution_id,
            school_name=e.school_name,
            year=e.year,
            kind=e.kind,
            prompt=e.prompt,
            title=e.title,
            body=e.body,
            word_count=e.word_count,
            source_url=e.source_url,
            source_name=e.source_name,
            tags=list(e.tags),
            notes=e.notes,
            status=e.status,
            language=e.language,
            created_by=e.created_by,
            updated_by=e.updated_by,
            created_at=e.created_at,
            updated_at=e.updated_at,
            lock_version=e.lock_version,
        )


class ExemplarListOut(BaseModel):
    """A page of exemplars for curators."""

    items: list[ExemplarOut]
    total: int


class ExemplarImportOut(BaseModel):
    """New drafts and the ids of exemplars that were already there."""

    created: list[ExemplarOut]
    duplicates: list[UUID]


class ExemplarExcerptOut(BaseModel):
    """What a student sees: an excerpt of about 80 words and the source."""

    id: UUID
    institution_id: UUID | None
    school_name: str
    year: int | None
    kind: Kind
    prompt: str
    title: str
    excerpt: str
    word_count: int
    source_url: str
    source_name: str
    tags: list[str]
    language: str

    @classmethod
    def of(cls, e: ExemplarPublic) -> "ExemplarExcerptOut":
        """Map the application view."""
        return cls(
            id=e.id,
            institution_id=e.institution_id,
            school_name=e.school_name,
            year=e.year,
            kind=e.kind,
            prompt=e.prompt,
            title=e.title,
            excerpt=e.excerpt,
            word_count=e.word_count,
            source_url=e.source_url,
            source_name=e.source_name,
            tags=list(e.tags),
            language=e.language,
        )


class ExemplarExcerptListOut(BaseModel):
    """A page of excerpts."""

    items: list[ExemplarExcerptOut]
    total: int


_FORBIDDEN = {403: {"model": ProblemOut, "description": "No exemplars:curate."}}
_NOT_FOUND = {404: {"model": ProblemOut, "description": "No such exemplar."}}
_INVALID = {422: {"model": ProblemOut, "description": "A field breaks a rule."}}
_DUPLICATE = {
    409: {"model": ProblemOut, "description": "Same source link and title exist."}
}
_LIMITED = {429: {"model": ProblemOut, "description": "Token write limit reached."}}

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def list_exemplars(
    container: ContainerDep,
    ctx: AnyContext,
    exemplar_status: Annotated[Status | None, Query(alias="status")] = None,
    kind: Kind | None = None,
    institution_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ExemplarListOut:
    """The library with bodies, newest first (exemplars:curate)."""
    page = await container.admission.exemplars.list(
        ctx,
        status=exemplar_status,
        kind=kind,
        institution_id=institution_id,
        query=q,
        limit=limit,
        offset=offset,
    )
    return ExemplarListOut(
        items=[ExemplarOut.of(e) for e in page.items], total=page.total
    )


async def create_exemplar(
    body: ExemplarIn, container: ContainerDep, ctx: AnyContext
) -> ExemplarOut:
    """Add an exemplar; a catalog token always creates a draft."""
    item = await container.admission.exemplars.create(ctx, body.to_input())
    return ExemplarOut.of(item)


async def import_exemplars(
    body: ExemplarImportIn, container: ContainerDep, ctx: AnyContext
) -> ExemplarImportOut:
    """Import up to 50 drafts; duplicates by (source_url, title) are skipped."""
    out = await container.admission.exemplars.import_many(
        ctx, [i.to_input() for i in body.items]
    )
    return ExemplarImportOut(
        created=[ExemplarOut.of(e) for e in out.created],
        duplicates=list(out.duplicates),
    )


async def get_exemplar(
    exemplar_id: UUID, container: ContainerDep, ctx: AnyContext
) -> ExemplarOut:
    """One exemplar with its body (exemplars:curate)."""
    return ExemplarOut.of(await container.admission.exemplars.get(ctx, exemplar_id))


async def patch_exemplar(
    exemplar_id: UUID,
    body: ExemplarPatchIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> ExemplarOut:
    """Edit, publish (status=published) or archive an exemplar."""
    item = await container.admission.exemplars.update(
        ctx, exemplar_id, body.changes(), lock_version=body.lock_version
    )
    return ExemplarOut.of(item)


async def delete_exemplar(
    exemplar_id: UUID, container: ContainerDep, ctx: AnyContext
) -> None:
    """Delete an exemplar for good."""
    await container.admission.exemplars.delete(ctx, exemplar_id)


async def list_public_exemplars(
    container: ContainerDep,
    ctx: AdmissionCtx,
    kind: Kind | None = None,
    institution_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ExemplarExcerptListOut:
    """Published exemplars as 80-word excerpts with their source."""
    page = await container.admission.exemplars.list_public(
        ctx,
        kind=kind,
        institution_id=institution_id,
        query=q,
        limit=limit,
        offset=offset,
    )
    return ExemplarExcerptListOut(
        items=[ExemplarExcerptOut.of(e) for e in page.items], total=page.total
    )


async def get_public_exemplar(
    exemplar_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ExemplarExcerptOut:
    """One published exemplar as an excerpt; a draft answers 404."""
    out = await container.admission.exemplars.get_public(ctx, exemplar_id)
    return ExemplarExcerptOut.of(out)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_STAFF = "/staff/exemplars"
_route(
    _STAFF,
    list_exemplars,
    "GET",
    "list_exemplars",
    response_model=ExemplarListOut,
    responses={**_FORBIDDEN},
)
_route(
    _STAFF,
    create_exemplar,
    "POST",
    "create_exemplar",
    response_model=ExemplarOut,
    status_code=status.HTTP_201_CREATED,
    responses={**_FORBIDDEN, **_INVALID, **_DUPLICATE, **_LIMITED},
)
_route(
    f"{_STAFF}/import",
    import_exemplars,
    "POST",
    "import_exemplars",
    response_model=ExemplarImportOut,
    responses={**_FORBIDDEN, **_INVALID, **_LIMITED},
)
_route(
    f"{_STAFF}/{{exemplar_id}}",
    get_exemplar,
    "GET",
    "get_exemplar",
    response_model=ExemplarOut,
    responses={**_FORBIDDEN, **_NOT_FOUND},
)
_route(
    f"{_STAFF}/{{exemplar_id}}",
    patch_exemplar,
    "PATCH",
    "patch_exemplar",
    response_model=ExemplarOut,
    responses={
        **_FORBIDDEN,
        **_NOT_FOUND,
        **_INVALID,
        409: {
            "model": ProblemOut,
            "description": "Stale lock_version or duplicate link and title.",
        },
    },
)
_route(
    f"{_STAFF}/{{exemplar_id}}",
    delete_exemplar,
    "DELETE",
    "delete_exemplar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_FORBIDDEN, **_NOT_FOUND},
)
_route(
    "/exemplars",
    list_public_exemplars,
    "GET",
    "list_public_exemplars",
    response_model=ExemplarExcerptListOut,
)
_route(
    "/exemplars/{exemplar_id}",
    get_public_exemplar,
    "GET",
    "get_public_exemplar",
    response_model=ExemplarExcerptOut,
    responses={**_NOT_FOUND},
)
