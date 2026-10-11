"""Use cases of web search: the daily quota and the search itself (NB-32, NB-33).

`chat` and `fast` make one Exa search. `deep` plans several queries with the model,
searches them at once, merges the pages and lets the model rank them with a reason
each. Quota units are searches: one for `chat` and `fast`, `web_search_deep_queries`
for `deep`. They are taken before the call (an atomic increment, so two requests at
once cannot both pass the limit) and given back when the provider fails or when Exa
timed out with nothing found. Tokens of the model calls are not counted in the AI
budgets; the daily search count is the control, and the Exa charge is in the outcome
(`cost_micro`) for the usage ledger.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from app.modules.ai.application.web_pages import LocalPage, WebPageIndex
from app.modules.ai.domain.db_first import judge
from app.modules.ai.domain.web_prompts import (
    PLAN_SCHEMA,
    PLAN_SCHEMA_NAME,
    PLAN_SYSTEM,
    RANK_SCHEMA,
    RANK_SCHEMA_NAME,
    RANK_SYSTEM,
    plan_request,
    rank_request,
)
from app.modules.ai.ports.search_quota import SearchQuotaStore
from app.modules.ai.ports.usage import FreeUsage
from app.settings import LimitsSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.ai_tasks import AiTask
from app.shared.clock import TASHKENT, Clock, local_today
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError, LlmGateway
from app.shared.contracts.web_search import (
    PlatformPassage,
    PlatformSearch,
    SearchCall,
    SearchNotice,
    SearchReply,
    WebHit,
    WebQuota,
    WebSearchDisabledError,
    WebSearchGateway,
    WebSearchKind,
    WebSearchOutcome,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)
from app.shared.features import Feature, is_enabled
from app.shared.limits import LimitsProvider, StaticLimits
from app.shared.web_citations import clean_text, url_key
from app.shared.web_urls import normalise_web_url

import structlog

log = structlog.get_logger(__name__)

QUERY_CHARS = 300
PLAN_QUERY_CHARS = 150
RANK_CANDIDATES = 30
RANK_TOKENS = 1200
PLAN_TOKENS = 300
JSON_TIMEOUT_SECONDS = 30.0
WHY_CHARS = 220


@dataclass(frozen=True, slots=True)
class _Ran:
    """The result of the search itself, before the quota is read again."""

    hits: tuple[WebHit, ...]
    queries: tuple[str, ...]
    cost_micro: int = 0
    notice: SearchNotice | None = None


def language_of(locale: str) -> str:
    """The search language of a locale (`uz`, `ru` or `en`)."""
    return locale if locale in {"uz", "ru", "en"} else "en"


class WebSearchService:
    """Implements `app.shared.contracts.web_search.WebSearchApi`."""

    def __init__(
        self,
        *,
        store: SearchQuotaStore,
        gateway: WebSearchGateway,
        llm: LlmGateway,
        clock: Clock,
        settings: Settings,
        platform: PlatformSearch | None = None,
        limits: LimitsProvider | None = None,
        pages: WebPageIndex | None = None,
        usage: FreeUsage | None = None,
    ) -> None:
        """Store the collaborators.

        `platform` turns on database-first search, `pages` the search over stored pages.
        """
        self.platform = platform
        self.store = store
        self.gateway = gateway
        self.llm = llm
        self.clock = clock
        self.settings = settings
        self.limits = limits or StaticLimits(settings.limits)
        self.pages = pages
        self.usage = usage

    # - - - quota - - -

    def _switched_on(self) -> bool:
        return is_enabled(self.settings, Feature.WEB_SEARCH)

    async def limit_of(self, actor: Actor) -> int | None:
        """Searches a day of the actor; None for staff (no quota, still counted).

        Students get their limit from the provider (the admin's value, their extension).
        """
        limits = await self.limits.for_actor(actor)
        student: int | None = limits.web_search_per_day_student
        staff: int | None = limits.web_search_per_day_staff
        return student if actor.has(Role.STUDENT) else staff

    async def cost_of(self, kind: WebSearchKind) -> int:
        """Quota units of a request: one search, or all the queries of a deep run."""
        limits = await self.limits.current()
        return limits.web_search_deep_queries if kind == "deep" else 1

    def _midnight(self) -> datetime:
        tomorrow = local_today(self.clock) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT).astimezone(UTC)

    async def quota(self, actor: Actor) -> WebQuota:
        """Today's searches of the actor."""
        limit = await self.limit_of(actor)
        used = await self.store.used(actor.user_id, local_today(self.clock))
        limits = await self.limits.current()
        return WebQuota(
            enabled=self._switched_on() and (limit is None or limit > 0),
            used=used if limit is None else min(used, limit),
            limit=limit,
            resets_at=self._midnight(),
            max_results=limits.web_search_max_results,
            deep_cost=limits.web_search_deep_queries,
        )

    async def _take(self, actor: Actor, units: int) -> None:
        """Take `units` from today's quota or raise; nothing stays taken on a raise."""
        limit = await self.limit_of(actor)
        if not self._switched_on() or (limit is not None and limit <= 0):
            raise WebSearchDisabledError()
        day = local_today(self.clock)
        total = await self.store.add(actor.user_id, day, units)
        if limit is not None and total > limit:
            await self.store.remove(actor.user_id, day, units)
            raise WebSearchQuotaError(
                params={
                    "limit": limit,
                    "left": max(limit - (total - units), 0),
                    "needed": units,
                    "resets_at": self._midnight().isoformat(),
                }
            )

    async def _give_back(self, actor: Actor, units: int) -> None:
        await self.store.remove(actor.user_id, local_today(self.clock), units)

    # - - - search - - -

    async def search(
        self,
        actor: Actor,
        *,
        query: str,
        locale: str,
        kind: WebSearchKind = "chat",
        known_urls: frozenset[str] = frozenset(),
    ) -> WebSearchOutcome:
        """Answer from stored pages when they are enough, else search.

        Otherwise the quota is taken, the search runs and the stored ones that still fit
        are merged in.

        `known_urls` (normalised) are the pages the student already has; they are not
        new, so they never count toward `web_search_local_min_new`.
        """
        text = clean_text(query, QUERY_CHARS)
        units = await self.cost_of(kind)
        limit = await self.limit_of(actor)
        if not self._switched_on() or (limit is not None and limit <= 0):
            raise WebSearchDisabledError()
        local, enough = await self._from_database(actor, text)
        if enough:
            log.info("web_search_skipped", kind=kind, db_hits=len(local))
            await self._note_free("local")
            return WebSearchOutcome(
                hits=local,
                queries=(text,),
                quota=await self.quota(actor),
                web_skipped=True,
            )
        limits = await self.limits.current()
        wanted = _results_of(kind, limits)
        stored = await self._stored(text, kind, wanted, known_urls, limits)
        if stored is not None and len(stored) >= limits.web_search_local_min_new:
            shown = stored[:wanted]
            served: tuple[str, ...] = tuple(
                dict.fromkeys(page.source for page in shown)
            )
            log.info(
                "web_search_local",
                kind=kind,
                new=len(stored),
                hits=len(shown),
                sources=served,
                cost_micro=0,
            )
            await self._note_free(
                "cache" if all(p.source == "cache" for p in shown) else "local"
            )
            return WebSearchOutcome(
                hits=local + tuple(page.hit for page in shown),
                queries=(text,),
                quota=await self.quota(actor),
                sources=(("db",) if local else ()) + served,
            )
        await self._take(actor, units)
        try:
            ran = await self._run(text, language_of(locale), kind)
        except WebSearchUnavailableError:
            await self._give_back(actor, units)
            raise
        if ran.notice is not None and not ran.hits:
            await self._give_back(actor, units)  # Exa was too slow: nothing to pay for
        merged, sources = _with_stored(ran.hits, stored or [], wanted)
        log.info(
            "web_search_request",
            kind=kind,
            units=units,
            queries=len(ran.queries),
            hits=len(merged),
            local_new=len(stored or []),
            sources=sources,
            cost_micro=ran.cost_micro,
            notice=ran.notice,
        )
        return WebSearchOutcome(
            hits=local + tuple(merged),
            queries=ran.queries,
            quota=await self.quota(actor),
            cost_micro=ran.cost_micro,
            notice=ran.notice,
            sources=(("db",) if local else ()) + sources,
        )

    async def _note_free(self, model: str) -> None:
        """Put a search answered without Exa into the usage ledger at zero cost.

        Best effort: the answer does not wait for the ledger.
        """
        if self.usage is None:
            return
        try:
            await self.usage.note_free(task=AiTask.WEB_SEARCH.value, model=model)
        except Exception:
            log.warning("web_search_usage_note_failed")

    async def _stored(
        self,
        query: str,
        kind: WebSearchKind,
        wanted: int,
        known_urls: frozenset[str],
        limits: LimitsSettings,
    ) -> list[LocalPage] | None:
        """The stored pages that answer the query and are new to the student.

        None when the stored pages are not used (`web_search_local_min_new` is 0).
        """
        if self.pages is None or limits.web_search_local_min_new <= 0:
            return None
        # The size of the Exa calls of this kind (the cache key of their answers).
        size = (
            limits.web_search_max_results
            if kind == "chat"
            else limits.web_search_discover_results
        )
        return await self.pages.candidates(
            query,
            params=self._params(size),
            known=known_urls,
            limit=max(wanted, limits.web_search_local_min_new),
        )

    def _params(self, results: int) -> dict[str, object]:
        """What changes the results of one Exa search (the cache key with the query)."""
        return {
            "n": results,
            "type": self.settings.exa.search_type,
            "x": list(self.settings.web_search.blocked_domains),
        }

    async def _from_database(
        self, actor: Actor, query: str
    ) -> tuple[tuple[WebHit, ...], bool]:
        """Dense platform passages as hits, and whether they make the web needless."""
        cfg = self.settings.web_search.db_first
        if self.platform is None or not cfg.enabled:
            return (), False
        try:
            found = await self.platform.search(actor, query, cfg.candidates)
        except Exception:  # best effort: the web still answers
            log.warning("web_search_db_first_failed")
            return (), False
        verdict = judge(
            found,
            query,
            min_density=cfg.min_density,
            min_coverage=cfg.min_coverage,
            min_passages=cfg.min_passages,
        )
        return tuple(_db_hit(p) for p in verdict.dense), verdict.sufficient

    async def _run(self, query: str, language: str, kind: WebSearchKind) -> _Ran:
        limits = await self.limits.current()
        if kind == "chat":
            reply = await self._call(
                query, language, AiTask.WEB_SEARCH, limits.web_search_max_results, False
            )
            return _Ran(reply.hits, (query,), reply.cost_micro, reply.notice)
        if kind == "fast":
            reply = await self._call(
                query,
                language,
                AiTask.DISCOVER,
                limits.web_search_discover_results,
                True,
            )
            return _Ran(reply.hits, (query,), reply.cost_micro, reply.notice)
        return await self._deep(query, language)

    async def _call(
        self, query: str, language: str, task: AiTask, max_results: int, explain: bool
    ) -> SearchReply:
        call = SearchCall(
            query=query,
            language=language,
            max_results=max_results,
            explain=explain,
            profile=self.settings.ai_profile(task),
            exclude_domains=self.settings.web_search.blocked_domains,
        )
        reply = await self.gateway.search(call)
        await self._remember(query, max_results, reply.hits)
        return reply

    async def _remember(
        self, query: str, max_results: int, hits: tuple[WebHit, ...]
    ) -> None:
        """Keep the pages of an answer for later searches, best effort.

        The answer goes out either way.
        """
        if self.pages is None or not hits:
            return
        try:
            await self.pages.remember(
                query, params=self._params(max_results), hits=hits
            )
        except Exception:  # the answer does not wait for the store
            log.warning("web_pages_remember_failed", pages=len(hits))

    # - - - deep - - -

    async def _deep(self, query: str, language: str) -> _Ran:
        limits = await self.limits.current()
        count = limits.web_search_deep_queries
        queries = await self._plan(query, language, count)
        replies = await asyncio.gather(
            *(
                self._call(
                    q,
                    language,
                    AiTask.DISCOVER,
                    limits.web_search_discover_results,
                    True,
                )
                for q in queries
            ),
            return_exceptions=True,
        )
        good = [r for r in replies if isinstance(r, SearchReply)]
        failed = [r for r in replies if isinstance(r, WebSearchUnavailableError)]
        for other in replies:
            if isinstance(other, BaseException) and not isinstance(
                other, WebSearchUnavailableError
            ):
                raise other
        if not good:
            raise failed[0]
        if failed:
            log.warning(
                "web_search_deep_partial", failed=len(failed), total=len(queries)
            )
        pool = _merge([reply.hits for reply in good])
        cost = sum(reply.cost_micro for reply in good)
        notice: SearchNotice | None = (
            "timeout" if all(reply.notice == "timeout" for reply in good) else None
        )
        if not pool:
            return _Ran((), tuple(queries), cost, notice)
        hits = await self._rank(query, language, pool)
        return _Ran(hits, tuple(queries), cost, notice)

    async def _plan(self, query: str, language: str, count: int) -> list[str]:
        """The request itself plus the queries the cheap model adds (best effort)."""
        queries = [query]
        profile = self.settings.ai_profile(AiTask.DISCOVER)
        try:
            reply = await self.llm.complete_json(
                model=profile.model,
                system=PLAN_SYSTEM,
                messages=[
                    {"role": "user", "content": plan_request(query, language, count)}
                ],
                schema_name=PLAN_SCHEMA_NAME,
                schema=PLAN_SCHEMA,
                max_tokens=profile.output_tokens(PLAN_TOKENS),
                provider=profile.provider(require_parameters=True),
                timeout_seconds=JSON_TIMEOUT_SECONDS,
                tuning=profile.tuning,
            )
        except (AiProviderError, AiInvalidOutputError):
            log.warning("web_search_plan_failed")
            return queries
        proposed = reply["data"].get("queries")
        for item in proposed if isinstance(proposed, list) else []:
            text = clean_text(str(item), PLAN_QUERY_CHARS)
            if text and text.lower() not in {q.lower() for q in queries}:
                queries.append(text)
        return queries[:count]

    async def _rank(
        self, query: str, language: str, pool: list[WebHit]
    ) -> tuple[WebHit, ...]:
        """Keep the best pages with the reason the cheap model gives (best effort)."""
        keep = (await self.limits.current()).web_search_deep_results
        pool = pool[:RANK_CANDIDATES]
        profile = self.settings.ai_profile(AiTask.DISCOVER)
        try:
            reply = await self.llm.complete_json(
                model=profile.model,
                system=RANK_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": rank_request(query, language, pool, keep),
                    }
                ],
                schema_name=RANK_SCHEMA_NAME,
                schema=RANK_SCHEMA,
                max_tokens=profile.output_tokens(RANK_TOKENS),
                provider=profile.provider(require_parameters=True),
                timeout_seconds=JSON_TIMEOUT_SECONDS,
                tuning=profile.tuning,
            )
        except (AiProviderError, AiInvalidOutputError):
            log.warning("web_search_rank_failed")
            return tuple(pool[:keep])
        ranked = _apply_ranking(pool, reply["data"].get("results"), keep)
        return ranked or tuple(pool[:keep])


def _results_of(kind: WebSearchKind, limits: LimitsSettings) -> int:
    """How many pages a search of this kind shows."""
    if kind == "chat":
        return limits.web_search_max_results
    if kind == "fast":
        return limits.web_search_discover_results
    return limits.web_search_deep_results


def _with_stored(
    found: Sequence[WebHit], stored: Sequence[LocalPage], limit: int
) -> tuple[list[WebHit], tuple[str, ...]]:
    """Merge the provider's pages (first, its ranking) with the stored new pages.

    The stored pages fill up to `limit` and are not among the provider's; the sources
    of the pages are returned with them.
    """
    seen: set[str] = set()
    merged: list[WebHit] = []
    sources: list[str] = []
    for hit in found:
        key = normalise_web_url(hit.url) or hit.url
        if key not in seen:
            seen.add(key)
            merged.append(hit)
    if merged:
        sources.append("exa")
    for page in stored:
        if len(merged) >= limit:
            break
        key = normalise_web_url(page.hit.url) or page.hit.url
        if key in seen:
            continue
        seen.add(key)
        merged.append(page.hit)
        if page.source not in sources:
            sources.append(page.source)
    return merged, tuple(sources)


def _db_hit(passage: PlatformPassage) -> WebHit:
    return WebHit(
        title=clean_text(passage.title, 200),
        url=passage.url,
        site=passage.site,
        snippet=clean_text(passage.text, 1200),
        origin="db",
        ref_kind=passage.ref_kind,
        ref_id=passage.ref_id,
    )


def _merge(groups: list[tuple[WebHit, ...]]) -> list[WebHit]:
    """Pages of all searches, the first search's first, without the same page twice."""
    seen: set[str] = set()
    merged: list[WebHit] = []
    for group in groups:
        for hit in group:
            key = url_key(hit.url)
            if key not in seen:
                seen.add(key)
                merged.append(hit)
    return merged


def _apply_ranking(pool: list[WebHit], items: object, keep: int) -> tuple[WebHit, ...]:
    """The pool in the model's order with its reasons; bad numbers are skipped."""
    ranked: list[WebHit] = []
    taken: set[int] = set()
    for item in items if isinstance(items, list) else []:
        index = item.get("index") if isinstance(item, dict) else None
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        if not 0 <= index < len(pool) or index in taken:
            continue
        taken.add(index)
        why = clean_text(str(item.get("why") or ""), WHY_CHARS) or pool[index].why
        ranked.append(pool[index].model_copy(update={"why": why}))
        if len(ranked) == keep:
            break
    return tuple(ranked)
