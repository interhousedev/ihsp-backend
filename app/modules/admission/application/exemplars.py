"""The exemplar essay library: curation by counselors, excerpts for students."""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ExemplarDuplicateError,
    ExemplarInvalidError,
)
from app.modules.admission.domain.exemplars import (
    EXCERPT_WORDS,
    EXEMPLAR_KINDS,
    EXEMPLAR_STATUSES,
    MAX_BODY_LEN,
    MAX_IMPORT,
    MAX_PROMPT_LEN,
    MAX_TITLE_LEN,
    Exemplar,
    check_tags,
    check_text,
    check_url,
    count_words,
    excerpt,
    invalid,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

CATALOG_SCOPE: Final = "admission:catalog"
TOKEN_WRITES_PER_DAY: Final = 200
_DAY_SECONDS: Final = 86400
MAX_NOTES_LEN: Final = 4000
MAX_NAME_LEN: Final = 200
MIN_YEAR: Final = 1990
MAX_YEAR: Final = 2100
_PATCHABLE: Final = frozenset(
    {
        "institution_id",
        "school_name",
        "year",
        "kind",
        "prompt",
        "title",
        "body",
        "source_url",
        "source_name",
        "tags",
        "notes",
        "language",
        "status",
    }
)


@dataclass(frozen=True, slots=True)
class ExemplarInput:
    """The fields of a new exemplar as the caller sent them."""

    kind: str
    title: str
    body: str
    source_url: str
    institution_id: UUID | None = None
    school_name: str = ""
    year: int | None = None
    prompt: str = ""
    source_name: str = ""
    tags: Sequence[str] = ()
    notes: str = ""
    language: str = "en"
    status: str = "draft"


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What an import did: new drafts and the ids of the duplicates it skipped."""

    created: tuple[Exemplar, ...]
    duplicates: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ExemplarPublic:
    """What a student sees: an excerpt and where the essay came from, no body."""

    id: UUID
    institution_id: UUID | None
    school_name: str
    year: int | None
    kind: str
    prompt: str
    title: str
    excerpt: str
    word_count: int
    source_url: str
    source_name: str
    tags: tuple[str, ...]
    language: str


@dataclass(frozen=True, slots=True)
class ExemplarPage:
    """One page of exemplars and the total of the filter."""

    items: tuple[Exemplar, ...]
    total: int


@dataclass(frozen=True, slots=True)
class ExemplarPublicPage:
    """One page of student-facing exemplars."""

    items: tuple[ExemplarPublic, ...]
    total: int


def public_view(item: Exemplar) -> ExemplarPublic:
    """The student-facing view of an exemplar."""
    return ExemplarPublic(
        id=item.id,
        institution_id=item.institution_id,
        school_name=item.school_name,
        year=item.year,
        kind=item.kind,
        prompt=item.prompt,
        title=item.title,
        excerpt=excerpt(item.body, EXCERPT_WORDS),
        word_count=item.word_count,
        source_url=item.source_url,
        source_name=item.source_name,
        tags=item.tags,
        language=item.language,
    )


class ExemplarService:
    """Add, edit, publish and import exemplars; list them for students."""

    def __init__(
        self, uow: UowFactory, clock: Clock, limiter: RateLimiter | None = None
    ) -> None:
        """Keep the unit-of-work factory, clock and the token write limiter."""
        self._uow = uow
        self._clock = clock
        self._limiter = limiter

    def can_curate(self, ctx: AdmissionContext) -> bool:
        """Whether the caller is an administrator or a live exemplar curator."""
        if Role.ADMIN in ctx.actor.roles:
            return True
        now = self._clock.now()
        return any(
            a.active_at(now)
            and KIND_ROLE.get(a.role.kind) in ctx.actor.roles
            and Permission.EXEMPLARS_CURATE in a.role.permissions
            for a in ctx.assignments
        )

    def _require(self, ctx: AdmissionContext) -> None:
        if not self.can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.EXEMPLARS_CURATE.value}
            )

    @staticmethod
    def _is_token(ctx: AdmissionContext) -> bool:
        return CATALOG_SCOPE in ctx.actor.scopes

    def _require_session(self, ctx: AdmissionContext) -> None:
        """Curate and refuse the catalog token (it only creates drafts)."""
        self._require(ctx)
        if self._is_token(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.EXEMPLARS_CURATE.value}
            )

    async def _hit(self, ctx: AdmissionContext) -> None:
        if self._limiter is not None and self._is_token(ctx):
            await self._limiter.hit(
                f"admission:exemplar_token:{ctx.user_id}",
                limit=TOKEN_WRITES_PER_DAY,
                window_seconds=_DAY_SECONDS,
            )

    @staticmethod
    def _checked(data: ExemplarInput, *, prefix: str = "") -> dict[str, Any]:
        """Validated column values of the input; a token never publishes."""
        try:
            if data.kind not in EXEMPLAR_KINDS:
                raise invalid("kind", "unknown")
            if data.status not in EXEMPLAR_STATUSES:
                raise invalid("status", "unknown")
            if data.year is not None and not MIN_YEAR <= data.year <= MAX_YEAR:
                raise invalid("year", "out_of_range")
            body = check_text("body", data.body, MAX_BODY_LEN)
            return {
                "institution_id": data.institution_id,
                "school_name": check_text(
                    "school_name", data.school_name, MAX_NAME_LEN, required=False
                ),
                "year": data.year,
                "kind": data.kind,
                "prompt": check_text(
                    "prompt", data.prompt, MAX_PROMPT_LEN, required=False
                ),
                "title": check_text("title", data.title, MAX_TITLE_LEN),
                "body": body,
                "word_count": count_words(body),
                "source_url": check_url(data.source_url),
                "source_name": check_text(
                    "source_name", data.source_name, MAX_NAME_LEN, required=False
                ),
                "tags": check_tags(data.tags),
                "notes": check_text("notes", data.notes, MAX_NOTES_LEN, required=False),
                "language": check_text("language", data.language, 5),
                "status": data.status,
            }
        except ExemplarInvalidError as e:
            if prefix:
                e.params["field"] = f"{prefix}.{e.params['field']}"
            raise

    def _build(self, ctx: AdmissionContext, values: dict[str, Any]) -> Exemplar:
        now = self._clock.now()
        if self._is_token(ctx):
            values = {**values, "status": "draft"}
        return Exemplar(
            id=new_id(),
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            created_at=now,
            updated_at=now,
            lock_version=0,
            **values,
        )

    async def create(self, ctx: AdmissionContext, data: ExemplarInput) -> Exemplar:
        """Add an exemplar; a catalog token always creates a draft."""
        self._require(ctx)
        values = self._checked(data)
        async with self._uow() as uow:
            repo = uow.exemplars
            if values[
                "institution_id"
            ] is not None and not await repo.institution_exists(
                values["institution_id"]
            ):
                raise invalid("institution_id", "unknown")
            dup = await repo.find_by_source(values["source_url"], values["title"])
            if dup is not None:
                raise ExemplarDuplicateError(params={"exemplar_id": str(dup)})
            await self._hit(ctx)
            item = self._build(ctx, values)
            await repo.add(item)
            uow.access.audit(self._event("exemplar.created", ctx, item))
            await uow.commit()
        return item

    async def import_many(
        self, ctx: AdmissionContext, items: Sequence[ExemplarInput]
    ) -> ImportResult:
        """Add up to MAX_IMPORT exemplars; ones already in the library are skipped."""
        self._require(ctx)
        if len(items) > MAX_IMPORT:
            raise invalid("items", f"too_many:{MAX_IMPORT}")
        checked = [self._checked(d, prefix=f"items[{i}]") for i, d in enumerate(items)]
        created: list[Exemplar] = []
        duplicates: list[UUID] = []
        seen: set[tuple[str, str]] = set()
        async with self._uow() as uow:
            repo = uow.exemplars
            await self._hit(ctx)
            await self._check_institutions(repo, checked)
            for values in checked:
                key = (values["source_url"], values["title"])
                dup = await repo.find_by_source(*key)
                if dup is not None:
                    duplicates.append(dup)
                    continue
                if key in seen:
                    continue
                seen.add(key)
                item = self._build(ctx, {**values, "status": "draft"})
                await repo.add(item)
                created.append(item)
            if created:
                uow.access.audit(
                    AuditEvent(
                        action="exemplar.imported",
                        actor_id=ctx.user_id,
                        student_id=None,
                        object_type="exemplar",
                        meta={
                            "created": len(created),
                            "duplicates": len(duplicates),
                            "token": self._is_token(ctx),
                        },
                    )
                )
            await uow.commit()
        return ImportResult(tuple(created), tuple(duplicates))

    async def _check_institutions(
        self, repo: Any, checked: list[dict[str, Any]]
    ) -> None:
        known: dict[UUID, bool] = {}
        for i, values in enumerate(checked):
            inst = values["institution_id"]
            if inst is not None and inst not in known:
                known[inst] = await repo.institution_exists(inst)
            if inst is not None and not known[inst]:
                raise invalid(f"items[{i}].institution_id", "unknown")

    async def update(
        self,
        ctx: AdmissionContext,
        exemplar_id: UUID,
        changes: dict[str, Any],
        *,
        lock_version: int,
    ) -> Exemplar:
        """Change the given fields (status included) of an exemplar."""
        self._require_session(ctx)
        unknown = set(changes) - _PATCHABLE
        if unknown:
            raise invalid(sorted(unknown)[0], "unknown_field")
        async with self._uow() as uow:
            repo = uow.exemplars
            current = await repo.get(exemplar_id)
            if current is None:
                raise AdmissionNotFoundError()
            merged = dataclasses.replace(
                ExemplarInput(
                    kind=current.kind,
                    title=current.title,
                    body=current.body,
                    source_url=current.source_url,
                    institution_id=current.institution_id,
                    school_name=current.school_name,
                    year=current.year,
                    prompt=current.prompt,
                    source_name=current.source_name,
                    tags=current.tags,
                    notes=current.notes,
                    language=current.language,
                    status=current.status,
                ),
                **changes,
            )
            values = self._checked(merged)
            inst = values["institution_id"]
            if (
                inst is not None
                and inst != current.institution_id
                and not await repo.institution_exists(inst)
            ):
                raise invalid("institution_id", "unknown")
            if (values["source_url"], values["title"]) != (
                current.source_url,
                current.title,
            ):
                dup = await repo.find_by_source(values["source_url"], values["title"])
                if dup is not None and dup != current.id:
                    raise ExemplarDuplicateError(params={"exemplar_id": str(dup)})
            updated = dataclasses.replace(
                current,
                **values,
                updated_by=ctx.user_id,
                updated_at=self._clock.now(),
            )
            if not await repo.update(updated, expected_lock=lock_version):
                raise AdmissionConflictError()
            action = (
                f"exemplar.{updated.status}"
                if updated.status != current.status
                else "exemplar.edited"
            )
            uow.access.audit(self._event(action, ctx, updated))
            await uow.commit()
        return dataclasses.replace(updated, lock_version=lock_version + 1)

    async def delete(self, ctx: AdmissionContext, exemplar_id: UUID) -> None:
        """Remove an exemplar for good."""
        self._require_session(ctx)
        async with self._uow() as uow:
            if not await uow.exemplars.delete(exemplar_id):
                raise AdmissionNotFoundError()
            uow.access.audit(
                AuditEvent(
                    action="exemplar.deleted",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="exemplar",
                    object_id=exemplar_id,
                )
            )
            await uow.commit()

    async def list(
        self,
        ctx: AdmissionContext,
        *,
        status: str | None,
        kind: str | None,
        institution_id: UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> ExemplarPage:
        """A page of the library with bodies, for curators."""
        self._require(ctx)
        async with self._uow() as uow:
            rows, total = await uow.exemplars.search(
                status=status,
                kind=kind,
                institution_id=institution_id,
                query=query,
                limit=limit,
                offset=offset,
            )
        return ExemplarPage(tuple(rows), total)

    async def get(self, ctx: AdmissionContext, exemplar_id: UUID) -> Exemplar:
        """One exemplar with its body, for curators."""
        self._require(ctx)
        async with self._uow() as uow:
            item = await uow.exemplars.get(exemplar_id)
        if item is None:
            raise AdmissionNotFoundError()
        return item

    async def list_public(
        self,
        ctx: AdmissionContext,
        *,
        kind: str | None,
        institution_id: UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> ExemplarPublicPage:
        """Published exemplars as excerpts."""
        async with self._uow() as uow:
            rows, total = await uow.exemplars.search(
                status="published",
                kind=kind,
                institution_id=institution_id,
                query=query,
                limit=limit,
                offset=offset,
            )
        return ExemplarPublicPage(tuple(public_view(r) for r in rows), total)

    async def get_public(
        self, ctx: AdmissionContext, exemplar_id: UUID
    ) -> ExemplarPublic:
        """One published exemplar as an excerpt; any other status is not found."""
        async with self._uow() as uow:
            item = await uow.exemplars.get(exemplar_id)
        if item is None or item.status != "published":
            raise AdmissionNotFoundError()
        return public_view(item)

    @staticmethod
    def _event(action: str, ctx: AdmissionContext, item: Exemplar) -> AuditEvent:
        return AuditEvent(
            action=action,
            actor_id=ctx.user_id,
            student_id=None,
            object_type="exemplar",
            object_id=item.id,
            meta={"kind": item.kind, "status": item.status},
        )
