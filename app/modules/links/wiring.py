"""Builds the links module services (container.links)."""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.links.application.add_lesson_resources import AddLessonResources
from app.modules.links.application.create_link import CreateLink
from app.modules.links.application.create_share import CreateShare
from app.modules.links.application.delete_lesson_resource import DeleteLessonResource
from app.modules.links.application.delete_link import DeleteLink
from app.modules.links.application.disable_link import DisableLink
from app.modules.links.application.dismiss_reports import DismissReports
from app.modules.links.application.flush_hits import FlushHits
from app.modules.links.application.get_public_message import GetPublicMessage
from app.modules.links.application.get_public_share import GetPublicShare
from app.modules.links.application.hide_lesson_resource import HideLessonResource
from app.modules.links.application.import_lesson_files import (
    ImportLessonFiles,
    PurgeEmisResources,
)
from app.modules.links.application.import_lesson_urls import ImportLessonUrls
from app.modules.links.application.lesson_access import LessonAccess
from app.modules.links.application.lesson_sources import (
    EmisImportHiding,
    EmisSourcesHiding,
    ListLessonSources,
)
from app.modules.links.application.link_creation_limit import LinkCreationLimit
from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.list_lesson_resources import ListLessonResources
from app.modules.links.application.list_moderation_queue import ListModerationQueue
from app.modules.links.application.list_my_links import ListMyLinks
from app.modules.links.application.moderation_views import ModerationViews
from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.open_short_link import OpenShortLink
from app.modules.links.application.public_api import LinksApiImpl
from app.modules.links.application.public_pages import PublicPages
from app.modules.links.application.release_slugs import ReleaseSlugs
from app.modules.links.application.render_room_page import RenderRoomPage
from app.modules.links.application.report_link import ReportLink
from app.modules.links.application.report_pages import ReportPages
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.revoke_link import RevokeLink
from app.modules.links.application.revoke_owner import RevokeOwner
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.room_day_builder import RoomDayBuilder
from app.modules.links.application.search_moderation import SearchModeration
from app.modules.links.application.share_message import ShareMessage
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.application.target_resolver import TargetResolver
from app.modules.links.domain.url_policy import UrlPolicy
from app.modules.links.infrastructure.blocklist import load_blocklist
from app.modules.links.infrastructure.hit_counter import RedisHitCounter
from app.modules.links.infrastructure.page_renderer import JinjaPageRenderer
from app.modules.links.infrastructure.pin_limiter import RedisPinLimiter
from app.modules.links.infrastructure.room_page_cache import RedisRoomPageCache
from app.modules.links.infrastructure.room_sessions import RedisRoomSessions
from app.modules.links.infrastructure.title_fetcher import HttpTitleFetcher
from app.modules.links.infrastructure.uow import LinksSqlUnitOfWork
from app.modules.links.ports.hit_counter import HitCounter
from app.modules.links.ports.page_renderer import PageRenderer
from app.modules.links.ports.pin_limiter import PinLimiter
from app.modules.links.ports.room_page_cache import RoomPageCache
from app.modules.links.ports.room_sessions import RoomSessions
from app.modules.links.ports.title_fetcher import TitleFetcher
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.contracts.academic import (
    LessonGroupIndex,
    LessonGroupRef,
    ScheduleQueries,
)
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.notebooks import NotebooksQueries
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class LinksServices:
    """Use cases of the links module and its public contract."""

    create_link: CreateLink
    list_my_links: ListMyLinks
    delete_link: DeleteLink
    revoke_link: RevokeLink
    create_share: CreateShare
    add_lesson_resources: AddLessonResources
    list_lesson_resources: ListLessonResources
    delete_lesson_resource: DeleteLessonResource
    hide_lesson_resource: HideLessonResource
    list_lesson_sources: ListLessonSources
    emis_sources_hiding: EmisSourcesHiding
    open_short_link: OpenShortLink
    get_public_share: GetPublicShare
    share_message: ShareMessage
    get_public_message: GetPublicMessage
    report_link: ReportLink
    report_pages: ReportPages
    list_moderation_queue: ListModerationQueue
    search_moderation: SearchModeration
    disable_link: DisableLink
    dismiss_reports: DismissReports
    render_room_page: RenderRoomPage
    flush_hits: FlushHits
    release_slugs: ReleaseSlugs
    revoke_owner: RevokeOwner
    public: LinksApiImpl


@dataclass(frozen=True, slots=True)
class LinksOverrides:
    """Replacements for infrastructure, used by tests only."""

    uow_factory: UowFactory | None = None
    title_fetcher: TitleFetcher | None = None
    rng: random.Random | None = None
    renderer: PageRenderer | None = None
    hit_counter: HitCounter | None = None
    room_cache: RoomPageCache | None = None
    pin_limiter: PinLimiter | None = None
    room_sessions: RoomSessions | None = None
    blocked_domains: frozenset[str] | None = None


class _NoLessonGroups:
    """Index used when the caller wires no schedule index: no lessons."""

    async def lesson_groups(
        self,
        *,
        subject_id: UUID | None = None,
        lesson_ids: Sequence[UUID] | None = None,
        teacher_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> list[LessonGroupRef]:
        """Return nothing."""
        return []


def build(
    deps: ModuleDeps,
    *,
    files: FilesApi,
    schedule: ScheduleQueries,
    identity: IdentityDirectory,
    ai: AiQueries,
    flashcards: FlashcardsApi,
    notebooks: NotebooksQueries,
    lesson_index: LessonGroupIndex | None = None,
    overrides: LinksOverrides | None = None,
) -> LinksServices:
    """Wire the use cases of the links module."""
    custom = overrides or LinksOverrides()

    def sql_uow() -> LinksSqlUnitOfWork:
        return LinksSqlUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    uow_factory: UowFactory = custom.uow_factory or sql_uow
    urls = LinkUrls(deps.settings.urls.short_links, deps.settings.urls.share)
    blocked = custom.blocked_domains
    policy = UrlPolicy(blocked if blocked is not None else load_blocklist())
    renderer = custom.renderer or JinjaPageRenderer(deps.i18n)
    hits = custom.hit_counter or RedisHitCounter(deps.redis)
    cache = custom.room_cache or RedisRoomPageCache(deps.redis)
    pin_limiter = custom.pin_limiter or RedisPinLimiter(deps.redis)
    room_sessions = custom.room_sessions or RedisRoomSessions(deps.redis)
    titles = custom.title_fetcher or HttpTitleFetcher()
    rng = custom.rng or random.SystemRandom()

    resolver = TargetResolver(files, policy, titles)
    allocator = SlugAllocator(rng)
    limit = LinkCreationLimit(deps.rate_limiter)
    builder = ResourceBuilder(files, identity, urls)
    invalidator = RoomCacheInvalidator(schedule, cache, deps.kicker)
    access = LessonAccess(schedule)
    index: LessonGroupIndex = lesson_index or _NoLessonGroups()
    import_hiding = EmisImportHiding(index)
    not_found = NotFoundCounter(deps.rate_limiter)
    pages = PublicPages(renderer, urls)
    moderation_views = ModerationViews(builder, identity)
    revoke_link = RevokeLink(
        uow_factory=uow_factory,
        clock=deps.clock,
        builder=builder,
        invalidator=invalidator,
    )
    add_resources = AddLessonResources(
        uow_factory=uow_factory,
        access=access,
        schedule=schedule,
        resolver=resolver,
        allocator=allocator,
        limit=limit,
        builder=builder,
        invalidator=invalidator,
        clock=deps.clock,
    )
    report_link = ReportLink(
        uow_factory=uow_factory,
        rate_limiter=deps.rate_limiter,
        not_found=not_found,
        clock=deps.clock,
    )
    return LinksServices(
        create_link=CreateLink(
            uow_factory=uow_factory,
            resolver=resolver,
            allocator=allocator,
            limit=limit,
            clock=deps.clock,
            urls=urls,
        ),
        list_my_links=ListMyLinks(uow_factory=uow_factory, builder=builder),
        delete_link=DeleteLink(revoke_link=revoke_link),
        revoke_link=revoke_link,
        create_share=CreateShare(
            uow_factory=uow_factory,
            ai=ai,
            flashcards=flashcards,
            notebooks=notebooks,
            allocator=allocator,
            limit=limit,
            clock=deps.clock,
            urls=urls,
        ),
        add_lesson_resources=add_resources,
        list_lesson_resources=ListLessonResources(
            uow_factory=uow_factory, access=access, builder=builder
        ),
        delete_lesson_resource=DeleteLessonResource(
            uow_factory=uow_factory,
            access=access,
            invalidator=invalidator,
            clock=deps.clock,
        ),
        hide_lesson_resource=HideLessonResource(
            uow_factory=uow_factory,
            access=access,
            builder=builder,
            invalidator=invalidator,
            clock=deps.clock,
        ),
        list_lesson_sources=ListLessonSources(
            uow_factory=uow_factory, index=index, builder=builder
        ),
        emis_sources_hiding=EmisSourcesHiding(
            uow_factory=uow_factory,
            index=index,
            invalidator=invalidator,
            clock=deps.clock,
        ),
        open_short_link=OpenShortLink(
            uow_factory=uow_factory,
            files=files,
            policy=policy,
            hits=hits,
            not_found=not_found,
            pages=pages,
            clock=deps.clock,
        ),
        get_public_share=GetPublicShare(
            uow_factory=uow_factory,
            ai=ai,
            flashcards=flashcards,
            notebooks=notebooks,
            identity=identity,
            hits=hits,
            not_found=not_found,
            clock=deps.clock,
        ),
        share_message=ShareMessage(
            uow_factory=uow_factory,
            ai=ai,
            allocator=allocator,
            limit=limit,
            clock=deps.clock,
            urls=urls,
        ),
        get_public_message=GetPublicMessage(
            uow_factory=uow_factory,
            ai=ai,
            hits=hits,
            not_found=not_found,
            clock=deps.clock,
        ),
        report_link=report_link,
        report_pages=ReportPages(
            uow_factory=uow_factory,
            report_link=report_link,
            not_found=not_found,
            pages=pages,
        ),
        list_moderation_queue=ListModerationQueue(
            uow_factory=uow_factory, views=moderation_views
        ),
        search_moderation=SearchModeration(
            uow_factory=uow_factory, views=moderation_views, identity=identity
        ),
        disable_link=DisableLink(
            uow_factory=uow_factory,
            views=moderation_views,
            invalidator=invalidator,
            clock=deps.clock,
        ),
        dismiss_reports=DismissReports(
            uow_factory=uow_factory, views=moderation_views, clock=deps.clock
        ),
        render_room_page=RenderRoomPage(
            uow_factory=uow_factory,
            schedule=schedule,
            identity=identity,
            builder=builder,
            day_builder=RoomDayBuilder(urls, deps.settings.urls.rooms),
            renderer=renderer,
            cache=cache,
            pin_limiter=pin_limiter,
            sessions=room_sessions,
            not_found=not_found,
            pages=pages,
            clock=deps.clock,
        ),
        flush_hits=FlushHits(uow_factory=uow_factory, hits=hits, clock=deps.clock),
        release_slugs=ReleaseSlugs(uow_factory=uow_factory, clock=deps.clock),
        revoke_owner=RevokeOwner(
            uow_factory=uow_factory, invalidator=invalidator, clock=deps.clock
        ),
        public=LinksApiImpl(
            uow_factory=uow_factory,
            builder=builder,
            add_resources=add_resources,
            import_urls=ImportLessonUrls(
                uow_factory=uow_factory,
                policy=policy,
                allocator=allocator,
                invalidator=invalidator,
                clock=deps.clock,
                hiding=import_hiding,
            ),
            import_files=ImportLessonFiles(
                uow_factory=uow_factory,
                allocator=allocator,
                invalidator=invalidator,
                clock=deps.clock,
                hiding=import_hiding,
            ),
            purge_emis=PurgeEmisResources(
                uow_factory=uow_factory, invalidator=invalidator
            ),
            clock=deps.clock,
        ),
    )
