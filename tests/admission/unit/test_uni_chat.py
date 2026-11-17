"""University chats: the default prompt auto-runs once; research reuses 14 days."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.uni_chat import UniChatService
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.uni_chat import (
    PAGE_TEXT_CHARS,
    CachedWeb,
    UniChatLink,
)
from app.modules.admission.ports.consent import AI
from app.shared.contracts.web_search import WebHit
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents, FakeStore, FakeUow
from tests.fakes.clock import FixedClock

import pytest

USER = new_id()
CTX: Any = SimpleNamespace(
    user_id=USER,
    actor=SimpleNamespace(user_id=USER),
    admission=SimpleNamespace(is_applicant=True),
)


class Repo:
    def __init__(self) -> None:
        self.links: dict[UUID, UniChatLink] = {}
        self.prompts: dict[UUID, str] = {}
        self.cache: dict[tuple[str, str], CachedWeb] = {}
        self.winner: UniChatLink | None = None

    async def link(self, student_id: UUID, institution_id: UUID) -> Any:
        return next(
            (
                x
                for x in self.links.values()
                if (x.student_id, x.institution_id) == (student_id, institution_id)
            ),
            None,
        )

    async def link_by_chat(self, chat_id: UUID) -> Any:
        return next((x for x in self.links.values() if x.chat_id == chat_id), None)

    async def add(self, link: UniChatLink) -> UniChatLink:
        if self.winner is not None:  # a concurrent open inserted first
            self.links[self.winner.id] = self.winner
            return self.winner
        self.links[link.id] = link
        return link

    async def relink(self, link: UniChatLink, old_chat_id: UUID) -> bool:
        self.links[link.id] = link
        return True

    async def claim_auto_run(self, link_id: UUID, now: dt.datetime) -> bool:
        link = self.links[link_id]
        if link.auto_ran_at is not None:
            return False
        link.auto_run_pending, link.auto_ran_at = False, now
        return True

    async def prompt(self, student_id: UUID) -> str | None:
        return self.prompts.get(student_id)

    async def set_prompt(self, student_id: UUID, text: str, now: dt.datetime) -> None:
        if text:
            self.prompts[student_id] = text
        else:
            self.prompts.pop(student_id, None)

    async def cached(self, kind: str, key: str) -> CachedWeb | None:
        return self.cache.get((kind, key))

    async def store(
        self, kind: str, key: str, payload: dict[str, Any], now: dt.datetime
    ) -> None:
        self.cache[(kind, key)] = CachedWeb(payload, now)

    async def erase(self, student_id: UUID) -> None:
        self.links = {k: v for k, v in self.links.items() if v.student_id != student_id}


class Chats:
    def __init__(self) -> None:
        self.started: list[UUID] = []
        self.discarded: list[UUID] = []

    async def start(self, actor: Any, title: str) -> UUID:
        self.started.append(new_id())
        return self.started[-1]

    async def alive(self, chat_id: UUID, owner_id: UUID) -> bool:
        return chat_id in self.started

    async def discard(self, actor: Any, chat_id: UUID) -> None:
        self.discarded.append(chat_id)


class Pages:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def read(self, urls: Any) -> dict[str, str]:
        self.calls.append(list(urls))
        return {u: "T" * 9000 for u in urls}


class Web:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, actor: Any, **kw: Any) -> Any:
        self.calls += 1
        hit = WebHit(title="Aid", url="https://u.edu/aid", site="u.edu", snippet="x")
        return SimpleNamespace(hits=(hit,))


class Access:
    async def resolve(self, ctx: Any, student_id: UUID) -> Any:
        return SimpleNamespace(owner=ctx.user_id == student_id)


def build(
    pages: Pages | None = None,
) -> tuple[UniChatService, Repo, Chats, Web, FixedClock, UUID]:
    store = FakeStore()
    inst = CatalogInstitution(new_id(), "u", "Uni", "US", None, "published")
    store.institutions[inst.id] = inst
    repo, chats, web, clock = Repo(), Chats(), Web(), FixedClock(NOW)
    svc = UniChatService(
        lambda: FakeUow(store),  # type: ignore[arg-type,return-value]
        Access(),  # type: ignore[arg-type]
        FakeConsents({USER: frozenset({AI})}),
        repo,
        chats,
        SimpleNamespace(),  # type: ignore[arg-type]
        web,  # type: ignore[arg-type]
        clock,
        pages,
    )
    return svc, repo, chats, web, clock, inst.id


async def test_default_prompt_auto_runs_once() -> None:
    svc, _, chats, _, _, inst = build()
    await svc.set_default_prompt(CTX, "What aid can I get?")
    first = await svc.open(CTX, inst)
    assert first.created and first.auto_run_pending
    run = await svc.claim_run(CTX, inst, auto=True)
    assert run is not None and run.prompt == "What aid can I get?"
    assert await svc.claim_run(CTX, inst, auto=True) is None
    again = await svc.open(CTX, inst)
    assert not again.created and not again.auto_run_pending
    assert again.chat_id == first.chat_id and len(chats.started) == 1
    manual = await svc.claim_run(CTX, inst, auto=False)
    assert manual is not None and manual.chat_id == first.chat_id


async def test_without_a_prompt_the_builtin_research_runs_once() -> None:
    svc, _, _, _, _, inst = build()
    opened = await svc.open(CTX, inst)
    assert opened.auto_run_pending
    run = await svc.claim_run(CTX, inst, auto=True, locale="ru")
    assert run is not None and run.prompt.startswith("Изучи этот университет")
    assert await svc.claim_run(CTX, inst, auto=True) is None
    assert not (await svc.open(CTX, inst)).auto_run_pending
    manual = await svc.claim_run(CTX, inst, auto=False)
    assert manual is not None and manual.prompt.startswith("Research this")


async def test_research_reuses_cache_for_14_days() -> None:
    svc, _, _, web, clock, inst = build()
    chat = (await svc.open(CTX, inst)).chat_id
    first = await svc.research(CTX.actor, chat, "Financial aid", "en")
    assert first is not None and web.calls == 1
    clock.advance(days=13)
    again = await svc.research(CTX.actor, chat, "financial  AID", "en")
    assert again is not None and again["cached"] and web.calls == 1
    clock.advance(days=2)
    await svc.research(CTX.actor, chat, "financial aid", "en")
    assert web.calls == 2


async def test_research_outside_a_uni_chat_is_none() -> None:
    svc, _, _, web, _, _ = build()
    assert await svc.research(CTX.actor, new_id(), "aid", "en") is None
    assert web.calls == 0


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_suggestions_are_localised(locale: str) -> None:
    svc, _, _, _, _, inst = build()
    items = await svc.suggestions(CTX, inst, locale)
    assert items and all(isinstance(x, str) and x for x in items)


async def test_losing_a_concurrent_open_discards_the_new_chat() -> None:
    svc, repo, chats, _, _, inst = build()
    repo.winner = UniChatLink(
        id=new_id(),
        student_id=USER,
        institution_id=inst,
        chat_id=new_id(),
        auto_run_pending=False,
        created_at=NOW,
    )
    opened = await svc.open(CTX, inst)
    assert not opened.created and opened.chat_id == repo.winner.chat_id
    assert chats.discarded == chats.started


async def test_research_reads_top_pages_and_reuses_them() -> None:
    pages = Pages()
    svc, _, _, _, clock, inst = build(pages)
    chat = (await svc.open(CTX, inst)).chat_id
    first = await svc.research(CTX.actor, chat, "aid", "en")
    assert first is not None and len(first["pages"][0]["text"]) == PAGE_TEXT_CHARS
    clock.advance(days=15)  # the search is stale, the page too
    await svc.research(CTX.actor, chat, "aid", "en")
    assert len(pages.calls) == 2
    clock.advance(days=1)
    await svc.research(CTX.actor, chat, "grants", "en")  # new search, fresh page
    assert len(pages.calls) == 2


async def test_is_uni_chat_only_for_the_owner() -> None:
    svc, _, _, _, _, inst = build()
    chat = (await svc.open(CTX, inst)).chat_id
    assert await svc.is_uni_chat(chat, USER)
    assert not await svc.is_uni_chat(chat, new_id())
    assert not await svc.is_uni_chat(new_id(), USER)
