"""Stored web pages: answer searches from pages already found, keep what Exa returns.

`candidates` gives the pages a query can be answered with, without Exa: the pages of
the query's cached answer, and the pages whose text is close to the question by
meaning (cosine, `exa.local_min_similarity`). `remember` keeps the pages of an Exa
answer and its order, so the next search can use them. `purge` deletes the pages and
the cached answers that are past their retention, with their vectors.

A page is found by its normalised URL (`app.shared.web_urls`), so a page returned again
is one row whose `last_seen_at` moves on, and a student's known sources are compared
with the same spelling.
"""

import hashlib
import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from app.modules.ai.ports.unit_of_work import UowFactory
from app.modules.ai.ports.web_pages import PageRecord, StoredPage
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.embeddings import EmbeddingIndex, TextToEmbed
from app.shared.contracts.web_search import WebHit
from app.shared.web_urls import normalise_web_url

import structlog

log = structlog.get_logger(__name__)

PURGE_BATCH = 500
CANDIDATE_POOL = 30  # nearest pages read before the known ones are dropped


def normalise_query(text: str) -> str:
    """Case, spacing and the end punctuation do not make another query."""
    flat = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return flat.strip(" ?!.;:")


def cache_key(query: str, params: Mapping[str, object]) -> str:
    """The sha256 of the normalised query and the parameters that change its results."""
    payload = json.dumps({"q": normalise_query(query), **params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def text_hash(text: str) -> str:
    """The content hash of a text, as `vectors.embeddings` keys it."""
    return hashlib.sha256(text.encode()).hexdigest()


def _embed_text(title: str, text: str, highlight: str, limit: int) -> str:
    return f"{title}\n{text}\n{highlight}".strip()[:limit]


@dataclass(frozen=True, slots=True)
class LocalPage:
    """A stored page that can answer the search, and why it was found."""

    hit: WebHit
    source: Literal["local", "cache"]
    similarity: float


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """What one purge deleted."""

    pages: int
    vectors: int
    queries: int


def _hit(page: StoredPage) -> WebHit:
    return WebHit(
        title=page.title,
        url=page.url,
        site=page.site,
        snippet=page.text,
        why=page.highlight,
        published_date=page.published_date,
    )


class WebPageIndex:
    """Use cases over stored pages; `embeddings` is late-bound (None: no vectors)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        embeddings: Callable[[], EmbeddingIndex | None],
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators; nothing is read or written here."""
        self.uow_factory = uow_factory
        self.embeddings = embeddings
        self.clock = clock
        self.settings = settings

    async def candidates(
        self,
        query: str,
        *,
        params: Mapping[str, object],
        known: frozenset[str],
        limit: int,
    ) -> list[LocalPage]:
        """The stored pages that answer the query, minus the ones the student has.

        The embedding of the question is made before the transaction opens: a slow
        provider must not hold a database transaction.
        """
        cfg = self.settings.exa
        index = self.embeddings()
        vector = await index.embed_query(query) if index is not None else None
        key = cache_key(query, params)
        since = self.clock.now() - timedelta(days=cfg.query_cache_days)
        async with self.uow_factory() as uow:
            cached: list[UUID] | None = None
            if cfg.query_cache_days > 0:
                cached = await uow.web_pages.cached(key, since)
            near: list[tuple[UUID, float]] = []
            if vector is not None:
                near = await uow.web_pages.nearest(
                    vector.model,
                    list(vector.values),
                    CANDIDATE_POOL,
                    cfg.local_min_similarity,
                )
            ids = list(dict.fromkeys([*(cached or []), *(page for page, _ in near)]))
            pages = await uow.web_pages.pages(ids)
        cached_ids = set(cached or [])
        similarity = dict(near)
        found: list[LocalPage] = []
        for page in pages:
            if page.url in known:
                continue
            source: Literal["local", "cache"] = (
                "cache" if page.id in cached_ids else "local"
            )
            found.append(LocalPage(_hit(page), source, similarity.get(page.id, 1.0)))
        return found[:limit]

    async def remember(
        self,
        query: str,
        *,
        params: Mapping[str, object],
        hits: Sequence[WebHit],
    ) -> tuple[UUID, ...]:
        """Keep the pages of an Exa answer and its order; their vectors follow.

        The rows are committed before the embedding: a provider failure there keeps the
        pages (they are found by their words later, and by meaning once embedded).
        """
        cfg = self.settings.exa
        records: list[PageRecord] = []
        texts: dict[str, str] = {}
        for hit in hits:
            url = normalise_web_url(hit.url)
            if url is None or url in texts or hit.origin != "web":
                continue
            body = hit.snippet[: cfg.page_text_chars]
            embed = _embed_text(hit.title, body, hit.why, cfg.page_text_chars)
            texts[url] = embed
            records.append(
                PageRecord(
                    url=url,
                    site=hit.site,
                    title=hit.title,
                    text=body,
                    highlight=hit.why,
                    published_date=hit.published_date,
                    content_hash=text_hash(embed),
                )
            )
        if not records:
            return ()
        now = self.clock.now()
        async with self.uow_factory() as uow:
            ids = await uow.web_pages.upsert(records, now)
            ordered = tuple(ids[record.url] for record in records)
            await uow.web_pages.put_query(
                cache_key(query, params), normalise_query(query), ordered, now
            )
        index = self.embeddings()
        if index is not None:
            to_embed = [
                TextToEmbed(content_hash=record.content_hash, text=texts[record.url])
                for record in records
            ]
            try:
                await index.ensure(to_embed)
            except AiProviderError:
                log.warning("web_pages_embed_failed", pages=len(to_embed))
        return ordered

    async def purge(self) -> PurgeReport:
        """Delete the expired pages and answers, in batches of 500.

        Pages not returned for `page_retention_days` go, and answers cached for longer
        than `query_cache_days`.
        """
        cfg = self.settings.exa
        now = self.clock.now()
        page_cutoff = now - timedelta(days=cfg.page_retention_days)
        query_cutoff = now - timedelta(days=cfg.query_cache_days)
        pages = vectors = queries = 0
        while True:
            async with self.uow_factory() as uow:
                deleted, removed = await uow.web_pages.purge_pages(
                    page_cutoff, PURGE_BATCH
                )
            pages += deleted
            vectors += removed
            if deleted < PURGE_BATCH:
                break
        while True:
            async with self.uow_factory() as uow:
                gone = await uow.web_pages.purge_queries(query_cutoff, PURGE_BATCH)
            queries += gone
            if gone < PURGE_BATCH:
                break
        report = PurgeReport(pages=pages, vectors=vectors, queries=queries)
        log.info("web_pages_purged", pages=pages, vectors=vectors, queries=queries)
        return report
