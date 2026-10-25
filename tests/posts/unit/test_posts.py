"""Posts: tree operations, cycles, audience, callback size, sanitizing, guest AI."""

from uuid import UUID

from app.interfaces.bot.routers.guest.callbacks import PostCb, StartModeCb
from app.modules.posts.application.admin_posts import PostDraft
from app.modules.posts.application.guest_assistant import (
    GUEST_TOOLS,
    SEARCH_TOOL,
    GuestLimits,
)
from app.modules.posts.domain.errors import (
    CycleError,
    GuestBusyError,
    GuestLimitError,
    HasChildrenError,
    InvalidPostError,
    ReorderMismatchError,
    RootProtectedError,
    SlugTakenError,
)
from app.modules.posts.domain.post import Audience, UrlButton, Viewer
from app.modules.posts.domain.sanitize import sanitize_telegram_html
from app.modules.posts.ports.repositories import GuestKnowledgeHit
from app.modules.posts.wiring import PostsServices
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.fakes.ai.llm import ScriptedLlm, text_reply, tool_reply
from tests.fakes.posts import FakeGuestKnowledge, fake_posts_services

import pytest
from uuid_utils.compat import uuid7

ADMIN = Actor(user_id=UUID(int=1), roles=frozenset({Role.ADMIN}))


def draft(slug: str, parent: UUID | None = None, **extra: object) -> PostDraft:
    """A small valid draft."""
    return PostDraft(
        slug=slug,
        title={"en": slug, "ru": slug},
        body={"en": "**Hello**"},
        parent_id=parent,
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def svc() -> PostsServices:
    """Posts services over fakes."""
    return fake_posts_services()


async def test_tree_creates_single_root(svc: PostsServices) -> None:
    first = await svc.admin.tree(ADMIN)
    second = await svc.admin.tree(ADMIN)
    assert first.post.is_root and first.post.id == second.post.id
    assert first.post.parent_id is None


async def test_create_appends_under_root_and_reorders(svc: PostsServices) -> None:
    a = await svc.admin.create(ADMIN, draft("a"))
    b = await svc.admin.create(ADMIN, draft("b"))
    root = await svc.admin.tree(ADMIN)
    assert [n.post.slug for n in root.children] == ["a", "b"]
    assert a.parent_id == root.post.id
    await svc.admin.reorder(ADMIN, None, [b.id, a.id])
    root = await svc.admin.tree(ADMIN)
    assert [n.post.slug for n in root.children] == ["b", "a"]
    with pytest.raises(ReorderMismatchError):
        await svc.admin.reorder(ADMIN, None, [b.id])


async def test_slug_unique_and_validation(svc: PostsServices) -> None:
    await svc.admin.create(ADMIN, draft("a"))
    with pytest.raises(SlugTakenError):
        await svc.admin.create(ADMIN, draft("a"))
    with pytest.raises(InvalidPostError):
        await svc.admin.create(ADMIN, draft("Bad Slug"))
    with pytest.raises(InvalidPostError):
        await svc.admin.create(
            ADMIN,
            PostDraft(slug="long", title={"en": "x"}, body={"en": "x" * 4001}),
        )
    with pytest.raises(InvalidPostError):
        UrlButton.of({"en": "site"}, "http://example.com")
    assert UrlButton.of({"en": "site"}, "https://iht.uz").url == "https://iht.uz"


async def test_delete_rules(svc: PostsServices) -> None:
    root = await svc.admin.tree(ADMIN)
    parent = await svc.admin.create(ADMIN, draft("p"))
    await svc.admin.create(ADMIN, draft("c", parent.id))
    with pytest.raises(RootProtectedError):
        await svc.admin.delete(ADMIN, root.post.id)
    with pytest.raises(HasChildrenError):
        await svc.admin.delete(ADMIN, parent.id)
    await svc.admin.delete(ADMIN, parent.id, cascade=True)
    assert (await svc.admin.tree(ADMIN)).children == []


async def test_move_prevents_cycles(svc: PostsServices) -> None:
    root = await svc.admin.tree(ADMIN)
    a = await svc.admin.create(ADMIN, draft("a"))
    b = await svc.admin.create(ADMIN, draft("b", a.id))
    c = await svc.admin.create(ADMIN, draft("c", b.id))
    with pytest.raises(CycleError):
        await svc.admin.move(ADMIN, a.id, c.id)
    with pytest.raises(CycleError):
        await svc.admin.move(ADMIN, a.id, a.id)
    with pytest.raises(RootProtectedError):
        await svc.admin.move(ADMIN, root.post.id, a.id)
    moved = await svc.admin.move(ADMIN, c.id, None)
    assert moved.parent_id == root.post.id


async def test_admin_role_required(svc: PostsServices) -> None:
    student = Actor(user_id=UUID(int=2), roles=frozenset({Role.STUDENT}))
    with pytest.raises(ForbiddenError):
        await svc.admin.tree(student)


async def test_audience_filtering(svc: PostsServices) -> None:
    g = await svc.admin.create(ADMIN, draft("g", audience=Audience.GUEST))
    await svc.admin.create(ADMIN, draft("s", audience=Audience.STUDENT))
    await svc.admin.create(ADMIN, draft("both"))
    await svc.admin.create(ADMIN, draft("hidden", published=False))
    inner = await svc.admin.create(ADMIN, draft("inner", g.id))
    guest = await svc.bot_posts.root(Viewer.GUEST)
    student = await svc.bot_posts.root(Viewer.STUDENT)
    assert [p.slug for p in guest.children] == ["g", "both"]
    assert [p.slug for p in student.children] == ["s", "both"]
    assert await svc.bot_posts.open(inner.id, Viewer.STUDENT) is None
    opened = await svc.bot_posts.open(inner.id, Viewer.GUEST)
    assert opened is not None and opened.parent_id == g.id


def test_callback_data_fits_64_bytes() -> None:
    packed = PostCb.of(uuid7()).pack()
    assert len(packed.encode()) <= 64
    assert PostCb.unpack(packed).post_id() is not None
    assert PostCb.of(None).post_id() is None
    assert len(StartModeCb(mode="student").pack().encode()) <= 64


def test_sanitize_keeps_telegram_tags_only() -> None:
    raw = (
        '<b>bold</b><script>alert(1)</script><a href="javascript:x">j</a>'
        '<a href="https://iht.uz">ok</a><img src=x><i>open'
    )
    clean = sanitize_telegram_html(raw)
    assert clean == '<b>bold</b>j<a href="https://iht.uz">ok</a><i>open</i>'


async def test_guest_assistant_has_only_knowledge_tool() -> None:
    llm = ScriptedLlm()
    llm.push(
        tool_reply((SEARCH_TOOL, {"query": "fees"})),
        tool_reply(("get_my_marks", {})),
        text_reply("Fees are on the site."),
    )
    knowledge = FakeGuestKnowledge([GuestKnowledgeHit("Fees", "See iht.uz")])
    svc = fake_posts_services(llm=llm, knowledge=knowledge)
    text = "".join(
        [d async for d in svc.guest_assistant.answer(1, "fees?", locale="en")]
    )
    assert text == "Fees are on the site."
    assert knowledge.queries == ["fees"]
    names = {t["function"]["name"] for t in GUEST_TOOLS}
    assert names == {SEARCH_TOOL}
    for request in llm.requests:
        assert request["tools"] in ([], [dict(t) for t in GUEST_TOOLS])
    unknown = llm.requests[2]["messages"][-1]
    assert unknown["role"] == "tool" and "unknown tool" in unknown["content"]
    assert "no access to any student" in llm.requests[0]["system"]


async def test_guest_limits() -> None:
    svc = fake_posts_services(
        limits=GuestLimits(per_minute=2, per_day=20, global_per_day=2000)
    )
    await svc.guest_assistant.check_limits(5)
    await svc.guest_assistant.check_limits(5)
    with pytest.raises(GuestLimitError):
        await svc.guest_assistant.check_limits(5)


async def test_guest_global_daily_ceiling_is_busy_for_every_guest() -> None:
    svc = fake_posts_services(
        limits=GuestLimits(per_minute=100, per_day=100, global_per_day=3)
    )
    for telegram_id in (1, 2, 3):
        await svc.guest_assistant.check_limits(telegram_id)
    with pytest.raises(GuestBusyError):
        await svc.guest_assistant.check_limits(4)
    with pytest.raises(GuestBusyError):
        await svc.guest_assistant.check_limits(1)
