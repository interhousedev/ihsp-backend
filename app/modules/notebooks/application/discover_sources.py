"""Use case: find web pages for a notebook, to add as URL sources (NB-31, § 1.5).

Discover only lists pages: nothing is fetched here. The student picks some and adds
them with the ordinary add-sources request (`kind: "url"`), which reads each page
through the SSRF-safe fetcher like any link.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.readers.url_reader import normalise_url
from app.modules.notebooks.domain.errors import (
    AutoNotebookReadOnlyError,
    InvalidOptionsError,
    SourceUnsupportedError,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.contracts.web_search import (
    DiscoverMode,
    SearchNotice,
    WebHit,
    WebQuota,
    WebSearchDisabledError,
)
from app.shared.web_citations import clean_text

QUERY_MIN_CHARS = 2
QUERY_MAX_CHARS = 300


@dataclass(frozen=True, slots=True)
class DiscoveredPage:
    """A page the search found, and whether the notebook already has it."""

    hit: WebHit
    already_added: bool


@dataclass(frozen=True, slots=True)
class DiscoverView:
    """The found pages, what was searched and today's searches left."""

    mode: DiscoverMode
    queries: tuple[str, ...]
    results: list[DiscoveredPage]
    quota: WebQuota
    notice: SearchNotice | None = None
    """`timeout`: the search provider was too slow; the searches were given back."""


def clean_query(text: str) -> str:
    """The request as one line of 2 to 300 characters.

    Raises:
        InvalidOptionsError: The request is empty, too short or too long.
    """
    flat = " ".join(text.split())
    if not QUERY_MIN_CHARS <= len(flat) <= QUERY_MAX_CHARS:
        raise InvalidOptionsError(
            params={"reason": "text-length", "max": QUERY_MAX_CHARS}
        )
    return clean_text(flat, QUERY_MAX_CHARS)


class DiscoverSources:
    """Searches the web for the request and marks the pages already in the notebook."""

    def __init__(self, core: NotebooksCore) -> None:
        """Store the shared services."""
        self.core = core

    async def execute(
        self, actor: Actor, notebook_id: UUID, query: str, mode: DiscoverMode = "fast"
    ) -> DiscoverView:
        """Run a `fast` (one search) or `deep` (several searches, ranked) search.

        Raises:
            NotebookNotFoundError: Not the student's notebook.
            AutoNotebookReadOnlyError: A subject or lesson notebook only takes notes.
            InvalidOptionsError: The request is empty or longer than 300 characters.
            WebSearchDisabledError: The feature is off or there is no search service.
            WebSearchQuotaError: Not enough searches are left today (`deep` costs
                several).
            WebSearchUnavailableError: The search provider failed (nothing is spent).
        """
        clean = clean_query(query)
        async with self.core.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            if notebook.is_auto:
                raise AutoNotebookReadOnlyError()
            known = await uow.sources.url_keys(notebook_id)
        api = self.core.web_search
        if api is None:
            raise WebSearchDisabledError()
        locale = await self.core.locale.locale_of(actor.user_id)
        outcome = await api.search(
            actor, query=clean, locale=locale, kind=mode, known_urls=known
        )
        async with self.core.uow_factory() as uow:
            results = [
                DiscoveredPage(hit, await self._added(uow, notebook_id, hit))
                for hit in outcome.hits
            ]
        return DiscoverView(
            mode, outcome.queries, results, outcome.quota, outcome.notice
        )

    @staticmethod
    async def _added(uow: NotebooksUnitOfWork, notebook_id: UUID, hit: WebHit) -> bool:
        """True when the notebook already has this page as a URL source."""
        try:
            key = f"url:{normalise_url(hit.url)}"
        except SourceUnsupportedError:
            return False
        return await uow.sources.ref_key_exists(notebook_id, key)
