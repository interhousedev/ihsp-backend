"""Sources, passages and the source pipeline of the notebooks module (NB-4 to NB-8)."""

import asyncio
from dataclasses import dataclass

from app.modules.notebooks.application.add_sources import AddSources
from app.modules.notebooks.application.build_source_guide import BuildSourceGuide
from app.modules.notebooks.application.discover_sources import DiscoverSources
from app.modules.notebooks.application.embed_passages import EmbedPassages
from app.modules.notebooks.application.gather_web_materials import GatherWebMaterials
from app.modules.notebooks.application.get_passage import GetPassage
from app.modules.notebooks.application.get_source import GetSource
from app.modules.notebooks.application.light_json import LightJson, Sleep
from app.modules.notebooks.application.list_passages import ListPassages
from app.modules.notebooks.application.list_sources import ListSources
from app.modules.notebooks.application.process_source import ProcessSource
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.refresh_summaries import RefreshSummaries
from app.modules.notebooks.application.remove_source import RemoveSource
from app.modules.notebooks.application.reread_source import RereadSource
from app.modules.notebooks.application.search_sources import SearchSources
from app.modules.notebooks.application.select_sources import SelectSources
from app.modules.notebooks.application.sweep_sources import SweepSources
from app.modules.notebooks.application.sync_source import SyncSource
from app.modules.notebooks.application.update_source import UpdateSource
from app.modules.notebooks.infrastructure.material_fetcher import HttpMaterialFetcher
from app.modules.notebooks.infrastructure.redis_guide_lock import RedisGuideLock
from app.modules.notebooks.infrastructure.web_fetcher import HttpWebFetcher
from app.modules.notebooks.ports.transcript import TranscriptProvider
from app.modules.notebooks.ports.web_fetcher import WebFetcher
from app.modules.notebooks.ports.web_materials import MaterialFetcher
from app.modules.notebooks.wiring_core import NotebooksCore
from app.settings import Settings
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibrarySourceReader
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader


@dataclass(frozen=True, slots=True)
class SourcesServices:
    """Use cases of sources and passages and their jobs (attribute = file name)."""

    add_sources: AddSources
    discover_sources: DiscoverSources
    list_sources: ListSources
    get_source: GetSource
    update_source: UpdateSource
    select_sources: SelectSources
    sync_source: SyncSource
    reread_source: RereadSource
    remove_source: RemoveSource
    list_passages: ListPassages
    get_passage: GetPassage
    search_sources: SearchSources
    process_source: ProcessSource
    embed_passages: EmbedPassages
    build_source_guide: BuildSourceGuide
    refresh_summaries: RefreshSummaries
    sweep_sources: SweepSources
    gather_web_materials: GatherWebMaterials
    readers: SourceReaders  # shared with the auto notebook sync


def build_sources(
    core: NotebooksCore,
    *,
    files: FilesApi,
    ai: AiQueries,
    links: LinksApi,
    schedule: ScheduleQueries,
    flashcards: FlashcardsApi,
    lms: LmsSourceReader | None,
    fetcher: WebFetcher | None,
    sleep: Sleep = asyncio.sleep,
    library: LibrarySourceReader | None = None,
    identity: IdentityDirectory | None = None,
    materials: MaterialFetcher | None = None,
    transcripts: TranscriptProvider | None = None,
) -> SourcesServices:
    """Build the source use cases over the shared services and other modules' APIs.

    `lms` and `fetcher` may be None: LMS steps and web pages are then unsupported.
    `library` (with `identity`, for the roles of the source owner) turns books and
    notes of the library into sources; without them those kinds are unsupported.
    `sleep` is the pause between retries of the light model (tests pass a fake).
    `materials` gathers the files of web sources; by default it is built over an
    `HttpWebFetcher`, and nothing is gathered without one.
    """
    deps = core.deps
    readers = SourceReaders(
        files=files,
        ai=ai,
        links=links,
        schedule=schedule,
        flashcards=flashcards,
        lms=lms,
        fetcher=fetcher,
        blocked_domains=deps.settings.web_search.blocked_domains,
        transcripts=transcripts,
        workspace=core.workspace,
        library=library,
        identity=identity,
        source_max_chars=deps.settings.notebooks.source_max_chars,
    )
    light = LightJson(llm=core.llm, budget=core.budget, sleep=sleep)
    return SourcesServices(
        add_sources=AddSources(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            rate_limiter=deps.rate_limiter,
            kicker=deps.kicker,
            readers=readers,
            limits=deps.effective_limits,
        ),
        discover_sources=DiscoverSources(core),
        list_sources=ListSources(uow_factory=core.uow_factory),
        get_source=GetSource(
            uow_factory=core.uow_factory, clock=deps.clock, readers=readers
        ),
        update_source=UpdateSource(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            kicker=deps.kicker,
        ),
        select_sources=SelectSources(uow_factory=core.uow_factory, clock=deps.clock),
        sync_source=SyncSource(
            uow_factory=core.uow_factory, clock=deps.clock, kicker=deps.kicker
        ),
        reread_source=RereadSource(
            uow_factory=core.uow_factory, clock=deps.clock, kicker=deps.kicker
        ),
        remove_source=RemoveSource(uow_factory=core.uow_factory, clock=deps.clock),
        list_passages=ListPassages(uow_factory=core.uow_factory),
        get_passage=GetPassage(uow_factory=core.uow_factory),
        search_sources=SearchSources(
            uow_factory=core.uow_factory,
            settings=deps.settings,
            rate_limiter=deps.rate_limiter,
            limits=deps.effective_limits,
        ),
        process_source=ProcessSource(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            readers=readers,
            kicker=deps.kicker,
        ),
        embed_passages=EmbedPassages(
            uow_factory=core.uow_factory,
            embeddings=core.embeddings,
            settings=deps.settings,
        ),
        build_source_guide=BuildSourceGuide(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            light=light,
            locale=core.locale,
            lock=RedisGuideLock(deps.redis),
            sleep=sleep,
        ),
        refresh_summaries=RefreshSummaries(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            light=light,
            locale=core.locale,
        ),
        sweep_sources=SweepSources(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            readers=readers,
            kicker=deps.kicker,
        ),
        gather_web_materials=GatherWebMaterials(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            settings=deps.settings,
            files=files,
            fetcher=materials or _materials(fetcher, deps.settings),
            model=light,
            counters=core.quota.store,
            limits=deps.effective_limits,
            kicker=deps.kicker,
            sleep=sleep,
        ),
        readers=readers,
    )


def _materials(
    fetcher: WebFetcher | None, settings: Settings
) -> MaterialFetcher | None:
    """The material gatherer over the SSRF-safe page fetcher, when there is one."""
    if not isinstance(fetcher, HttpWebFetcher):
        return None
    cfg = settings.notebooks
    return HttpMaterialFetcher(
        fetcher,
        min_image_px=cfg.web_materials_min_image_px,
        timeout_seconds=cfg.web_materials_timeout_seconds,
    )
