"""Administrators edit a draft and publish it."""

from collections.abc import Callable
from uuid import UUID

from app.modules.legal.domain.errors import (
    LegalIncompleteError,
    LegalInvalidError,
    LegalNoDraftError,
)
from app.modules.legal.domain.models import (
    KINDS,
    LOCALES,
    DocumentStatus,
    LegalDocument,
    kind_fits_scope,
)
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.legal import APP_SCOPES, GLOBAL_APP
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


def _texts(field: str, value: dict[str, str]) -> dict[str, str]:
    unknown = sorted(set(value) - set(LOCALES))
    if unknown:
        raise LegalInvalidError(params={"field": f"{field}.{unknown[0]}"})
    return {locale: text for locale, text in value.items() if text.strip()}


def _checked_series(kind: str, app_scope: str) -> None:
    if kind not in KINDS:
        raise LegalInvalidError(params={"field": "kind"})
    if app_scope not in APP_SCOPES or not kind_fits_scope(kind, app_scope):
        raise LegalInvalidError(params={"field": "app_scope"})


class SaveDraft:
    """Create or replace the draft of a kind; texts may still be incomplete."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        kind: str,
        *,
        title: dict[str, str],
        body_markdown: dict[str, str],
        announcement: dict[str, str] | None,
        app_scope: str = GLOBAL_APP,
    ) -> LegalDocument:
        """Upsert the draft of the kind in the scope and return it.

        Raises:
            LegalInvalidError: A text is keyed by an unknown locale, or the kind
                does not exist in the scope.
        """
        _checked_series(kind, app_scope)
        title = _texts("title", title)
        body = _texts("body_markdown", body_markdown)
        note = _texts("announcement", announcement) if announcement else None
        now = self._clock.now()
        async with self._uow_factory() as uow:
            await uow.legal.lock_kind(kind, app_scope)
            draft = await uow.legal.get_draft(kind, app_scope)
            if draft is None:
                draft = LegalDocument(
                    id=new_id(),
                    kind=kind,
                    app_scope=app_scope,
                    version=await uow.legal.next_version(kind, app_scope),
                    status=DocumentStatus.DRAFT,
                    title=title,
                    body_markdown=body,
                    announcement=note or None,
                    created_at=now,
                    updated_at=now,
                )
                await uow.legal.add(draft)
            else:
                draft.title, draft.body_markdown = title, body
                draft.announcement = note or None
                draft.updated_at = now
                await uow.legal.save(draft)
            await uow.commit()
        return draft


class PublishDraft:
    """Make the draft the current version; every user has to accept it."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        on_published: Callable[[], None] | None = None,
    ) -> None:
        """Store the dependencies; ``on_published`` drops cached consent passes."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._on_published = on_published

    async def execute(
        self, kind: str, *, actor_id: UUID, app_scope: str = GLOBAL_APP
    ) -> LegalDocument:
        """Publish the draft of the kind in the scope and return it.

        Raises:
            LegalInvalidError: The kind does not exist in the scope.
            LegalNoDraftError: The kind has no draft.
            LegalIncompleteError: A title or body is missing in some locale.
        """
        _checked_series(kind, app_scope)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            await uow.legal.lock_kind(kind, app_scope)
            draft = await uow.legal.get_draft(kind, app_scope)
            if draft is None:
                raise LegalNoDraftError(params={"kind": kind})
            missing = draft.missing_fields()
            if missing:
                raise LegalIncompleteError(params={"fields": ", ".join(missing)})
            draft.status = DocumentStatus.PUBLISHED
            draft.published_at = now
            draft.published_by = actor_id
            draft.updated_at = now
            await uow.legal.save(draft)
            uow.audit(
                AuditDraft(
                    type="legal.published",
                    actor_id=actor_id,
                    metadata={
                        "kind": kind,
                        "app_scope": app_scope,
                        "version": draft.version,
                    },
                )
            )
            await uow.commit()
        if self._on_published is not None:
            self._on_published()
        return draft
