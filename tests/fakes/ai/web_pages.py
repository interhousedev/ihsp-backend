"""In-memory web pages and a deterministic embedding index for the search tests.

The vectors are the fake embeddings of the ai module (word and trigram hashes), so two
texts that share words are close, and the same text is identical. Vectors are unit
length, so a dot product is the cosine similarity.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.modules.ai.infrastructure.fake_embeddings import fake_vector
from app.modules.ai.ports.web_pages import PageRecord, StoredPage
from app.shared.contracts.embeddings import EmbedReport, QueryVector, TextToEmbed

FAKE_MODEL = "fake-embedding"


@dataclass
class _Row:
    page: StoredPage
    content_hash: str
    last_seen_at: datetime
    times_returned: int


class InMemoryWebPageStore:
    """`WebPageStore` over dicts; `vectors` is the table of `vectors.embeddings`."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, _Row] = {}
        self.by_url: dict[str, UUID] = {}
        self.queries: dict[str, tuple[str, tuple[UUID, ...], datetime]] = {}
        self.vectors: dict[str, list[float]] = {}

    async def upsert(
        self, pages: Sequence[PageRecord], now: datetime
    ) -> dict[str, UUID]:
        """Insert new pages; a known URL keeps its id and counts one more return."""
        ids: dict[str, UUID] = {}
        for page in pages:
            known = self.by_url.get(page.url)
            if known is None:
                known = uuid4()
                self.by_url[page.url] = known
                self.rows[known] = _Row(
                    page=StoredPage(
                        id=known,
                        url=page.url,
                        site=page.site,
                        title=page.title,
                        text=page.text,
                        highlight=page.highlight,
                        published_date=page.published_date,
                    ),
                    content_hash=page.content_hash,
                    last_seen_at=now,
                    times_returned=1,
                )
            else:
                row = self.rows[known]
                row.page = StoredPage(
                    id=known,
                    url=page.url,
                    site=page.site,
                    title=page.title,
                    text=page.text,
                    highlight=page.highlight or row.page.highlight,
                    published_date=page.published_date or row.page.published_date,
                )
                row.content_hash = page.content_hash
                row.last_seen_at = now
                row.times_returned += 1
            ids[page.url] = known
        return ids

    async def pages(self, ids: Sequence[UUID]) -> list[StoredPage]:
        """The stored pages of the ids, in order."""
        return [self.rows[i].page for i in ids if i in self.rows]

    async def nearest(
        self, model: str, values: Sequence[float], limit: int, min_similarity: float
    ) -> list[tuple[UUID, float]]:
        """Cosine similarity (dot product of unit vectors), best first."""
        scored = []
        for page_id, row in self.rows.items():
            vector = self.vectors.get(row.content_hash)
            if vector is None:
                continue
            similarity = sum(a * b for a, b in zip(values, vector, strict=True))
            if similarity >= min_similarity:
                scored.append((page_id, similarity))
        scored.sort(key=lambda item: (-item[1], str(item[0])))
        return scored[:limit]

    async def cached(self, cache_key: str, since: datetime) -> list[UUID] | None:
        """The ordered ids of a query answered since `since`."""
        found = self.queries.get(cache_key)
        if found is None or found[2] < since:
            return None
        return list(found[1])

    async def put_query(
        self, cache_key: str, query: str, ids: Sequence[UUID], now: datetime
    ) -> None:
        """Remember the answer of a query."""
        self.queries[cache_key] = (query, tuple(ids), now)

    async def purge_pages(self, cutoff: datetime, limit: int) -> tuple[int, int]:
        """Delete up to `limit` pages last seen before `cutoff`, and unused vectors."""
        old = [i for i, row in self.rows.items() if row.last_seen_at < cutoff][:limit]
        hashes = {self.rows[i].content_hash for i in old}
        for page_id in old:
            url = self.rows.pop(page_id).page.url
            del self.by_url[url]
        used = {row.content_hash for row in self.rows.values()}
        removed = 0
        for content_hash in hashes - used:
            if self.vectors.pop(content_hash, None) is not None:
                removed += 1
        return len(old), removed

    async def purge_queries(self, cutoff: datetime, limit: int) -> int:
        """Delete up to `limit` cached queries answered before `cutoff`."""
        old = [key for key, (_, _, at) in self.queries.items() if at < cutoff][:limit]
        for key in old:
            del self.queries[key]
        return len(old)

    def page(self, url: str) -> StoredPage | None:
        """The stored page of a URL (for assertions)."""
        page_id = self.by_url.get(url)
        return self.rows[page_id].page if page_id is not None else None

    def returned(self, url: str) -> int:
        """How many times Exa returned the URL (for assertions)."""
        page_id = self.by_url.get(url)
        return self.rows[page_id].times_returned if page_id is not None else 0


class FakeEmbeddingIndex:
    """`EmbeddingIndex` with fake vectors, written into the store's vector table."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        """Share the vector table with the store."""
        self.vectors = vectors
        self.ensured: list[TextToEmbed] = []

    @property
    def model(self) -> str:
        """The fake model's name."""
        return FAKE_MODEL

    async def ensure(self, texts: Sequence[TextToEmbed]) -> EmbedReport:
        """Vectors of the texts that have none yet."""
        new = 0
        for item in texts:
            self.ensured.append(item)
            if item.content_hash not in self.vectors:
                self.vectors[item.content_hash] = fake_vector(item.text)
                new += 1
        return EmbedReport(embedded=new, already=len(texts) - new)

    async def embed_query(self, text: str) -> QueryVector | None:
        """The fake vector of a question."""
        if not text.strip():
            return None
        return QueryVector(model=FAKE_MODEL, values=fake_vector(text))
