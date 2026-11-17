"""University chats: open the chat, the default prompt, the brief and research.

A university chat is a fast-tier student chat of the AI module. Until research
has run in it once, opening it reports `auto_run_pending` and the client runs it
through `claim_run(auto=True)`: the student's default prompt, or the built-in
research prompt when they have none. The research tool reuses a
search or page younger than 14 days and spends the student's web quota otherwise.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
)
from app.modules.admission.domain.uni_chat import (
    PAGE,
    PAGE_TEXT_CHARS,
    PAGES_READ,
    PROMPT_LIMIT,
    SEARCH,
    UniChatLink,
    clean_prompt,
    hit_payload,
    is_fresh,
    page_key,
    render_brief,
    research_prompt,
    search_key,
    suggested_questions,
)
from app.modules.admission.ports.assistant import AssistantData
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.uni_chat import (
    UniChatRepository,
    UniChats,
    UniPageReader,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.web_search import WebSearchApi
from app.shared.ids import new_id
from app.shared.web_urls import normalise_web_url

_PERMISSION = "uni_chat:use"


@dataclass(frozen=True, slots=True)
class UniChatOpened:
    """The chat of a university; `auto_run_pending` asks the client to run it."""

    chat_id: UUID
    institution_id: UUID
    created: bool
    auto_run_pending: bool
    default_prompt: str | None


@dataclass(frozen=True, slots=True)
class UniChatRun:
    """What to send to the chat: the default prompt."""

    chat_id: UUID
    prompt: str


class UniChatService:
    """Admission side of the university chats (also the AI module's source)."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        consents: PurposeConsents,
        repo: UniChatRepository,
        chats: UniChats | None,
        data: AssistantData,
        web: WebSearchApi | None,
        clock: Clock,
        pages: UniPageReader | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._consents = consents
        self._repo = repo
        self._chats = chats
        self._data = data
        self._web = web
        self._clock = clock
        self._pages = pages

    async def _guard(self, ctx: AdmissionContext, *, ai: bool) -> None:
        if not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": _PERMISSION})
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": _PERMISSION})
        if ai and not await self._ai_allowed(ctx.user_id):
            raise ConsentRequiredError(params={"purpose": AI})

    async def _ai_allowed(self, user_id: UUID) -> bool:
        granted = (await self._consents.granted([user_id])).get(user_id, frozenset())
        return AI in granted

    async def _institution(self, institution_id: UUID) -> CatalogInstitution:
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
        if inst is None:
            raise AdmissionNotFoundError()
        return inst

    async def open(self, ctx: AdmissionContext, institution_id: UUID) -> UniChatOpened:
        """Return the student's chat of a university, creating it the first time."""
        await self._guard(ctx, ai=True)
        if self._chats is None:
            raise AdmissionForbiddenError(params={"permission": _PERMISSION})
        inst = await self._institution(institution_id)
        prompt = await self._repo.prompt(ctx.user_id)
        link = await self._repo.link(ctx.user_id, institution_id)
        if link is not None and await self._chats.alive(link.chat_id, ctx.user_id):
            return UniChatOpened(
                link.chat_id, institution_id, False, link.auto_ran_at is None, prompt
            )
        chat_id = await self._chats.start(ctx.actor, inst.name)
        if link is not None:  # the student deleted the chat: start a new one
            old = link.chat_id
            link.chat_id = chat_id
            link.auto_run_pending = link.auto_ran_at is None
            won = await self._repo.relink(link, old)
        else:
            link = await self._repo.add(
                UniChatLink(
                    id=new_id(),
                    student_id=ctx.user_id,
                    institution_id=institution_id,
                    chat_id=chat_id,
                    auto_run_pending=True,
                    created_at=self._clock.now(),
                )
            )
            won = link.chat_id == chat_id
        if not won:  # a concurrent open linked its chat first: drop ours
            await self._chats.discard(ctx.actor, chat_id)
            link = await self._repo.link(ctx.user_id, institution_id)
            if link is None:
                raise AdmissionNotFoundError()
        return UniChatOpened(
            link.chat_id, institution_id, won, link.auto_ran_at is None, prompt
        )

    async def claim_run(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        *,
        auto: bool,
        locale: str = "en",
    ) -> UniChatRun | None:
        """The research prompt to send; with `auto` only once (None after that).

        The student's default prompt, or the built-in one in `locale`.

        Raises:
            AdmissionNotFoundError: No chat yet.
        """
        await self._guard(ctx, ai=True)
        link = await self._repo.link(ctx.user_id, institution_id)
        if link is None:
            raise AdmissionNotFoundError()
        if auto and not await self._repo.claim_auto_run(link.id, self._clock.now()):
            return None
        prompt = await self._repo.prompt(ctx.user_id) or research_prompt(locale)
        return UniChatRun(link.chat_id, prompt)

    async def default_prompt(self, ctx: AdmissionContext) -> str | None:
        """Return the student's default prompt."""
        await self._guard(ctx, ai=False)
        return await self._repo.prompt(ctx.user_id)

    async def set_default_prompt(self, ctx: AdmissionContext, text: str) -> str | None:
        """Store the default prompt ("" removes it)."""
        await self._guard(ctx, ai=False)
        clean = clean_prompt(text)
        if len(clean) > PROMPT_LIMIT:
            raise CharLimitError(
                params={"field": "prompt", "limit": PROMPT_LIMIT, "count": len(clean)}
            )
        await self._repo.set_prompt(ctx.user_id, clean, self._clock.now())
        return clean or None

    async def suggestions(
        self, ctx: AdmissionContext, institution_id: UUID, locale: str
    ) -> list[str]:
        """Common questions about a university."""
        await self._guard(ctx, ai=False)
        inst = await self._institution(institution_id)
        async with self._uow() as uow:
            found = await uow.catalog.scholarships(institution_id=institution_id)
        return suggested_questions(inst, len(found), locale)

    # The AI module's `UniChatSource`.

    async def brief(self, chat_id: UUID, owner_id: UUID) -> str | None:
        """The university block of a chat's system prompt (None: not a uni chat)."""
        link = await self._repo.link_by_chat(chat_id)
        if link is None or link.student_id != owner_id:
            return None
        if not await self._ai_allowed(owner_id):
            return None
        async with self._uow() as uow:
            inst = await uow.catalog.institution(link.institution_id)
            if inst is None:
                return None
            found = await uow.catalog.scholarships(institution_id=inst.id)
            entry = await uow.shortlist.find(owner_id, inst.id)
        application = {
            "profile": await self._data.profile(owner_id),
            "test_scores": await self._data.test_scores(owner_id),
            "activities": await self._data.items(owner_id),
        }
        return render_brief(inst, found, entry, application)

    async def research(
        self, actor: Actor, chat_id: UUID, query: str, locale: str
    ) -> dict[str, Any] | None:
        """Pages about the chat's university; a search under 14 days is reused."""
        link = await self._repo.link_by_chat(chat_id)
        if link is None or link.student_id != actor.user_id:
            return None
        if self._web is None or not await self._ai_allowed(actor.user_id):
            return None
        async with self._uow() as uow:
            inst = await uow.catalog.institution(link.institution_id)
        if inst is None:
            return None
        key = search_key(inst.id, query)
        now = self._clock.now()
        hit = await self._repo.cached(SEARCH, key)
        if hit is not None and is_fresh(hit.fetched_at, now):
            return {**hit.payload, "cached": True}
        outcome = await self._web.search(
            actor, query=f"{inst.name} {query}", locale=locale, kind="fast"
        )
        pages = [hit_payload(h) for h in outcome.hits]
        await self._read_pages(pages, now)
        payload = {"university": inst.name, "pages": pages}
        await self._repo.store(SEARCH, key, payload, now)
        return {**payload, "cached": False}

    async def _read_pages(self, pages: list[dict[str, Any]], now: dt.datetime) -> None:
        """Add the full text of the top hits; a page read under 14 days ago is reused.

        Pages read now (and the other hits) are stored for 14 days.
        """
        unread: dict[str, dict[str, Any]] = {}
        reused: set[str] = set()
        for page in pages[:PAGES_READ]:
            known = await self._repo.cached(PAGE, page_key(_url(page)))
            if known and is_fresh(known.fetched_at, now) and known.payload.get("text"):
                page["text"] = known.payload["text"]
                reused.add(page["url"])
            else:
                unread[page["url"]] = page
        texts = await self._pages.read(list(unread)) if unread and self._pages else {}
        for url, page in unread.items():
            text = (texts.get(url) or "")[:PAGE_TEXT_CHARS]
            if text:
                page["text"] = text
        for page in pages:
            if page["url"] not in reused:
                await self._repo.store(PAGE, page_key(_url(page)), page, now)

    async def is_uni_chat(self, chat_id: UUID, owner_id: UUID) -> bool:
        """Whether the chat is the owner's university chat."""
        link = await self._repo.link_by_chat(chat_id)
        return link is not None and link.student_id == owner_id

    async def erase(self, student_id: UUID) -> None:
        """Forget the student's links and default prompt (privacy erasure)."""
        await self._repo.erase(student_id)


def _url(page: dict[str, Any]) -> str:
    """The cache form of a page's URL."""
    return normalise_web_url(page["url"]) or page["url"]
