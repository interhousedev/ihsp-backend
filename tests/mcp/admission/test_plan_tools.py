"""Plan, personal plan, calendar and activity-link tools of the admission server."""

import datetime as dt
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.admission.tools import (
    calendar,
    link_activity,
    personal_plan,
    plans,
)
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.calendar import FeedStatus, IssuedFeed
from app.modules.admission.application.personal_entries import PersonalAdded
from app.modules.admission.domain.calendar import CalendarEntry
from app.modules.admission.domain.personal_entries import PersonalEntry
from app.shared.actor import Actor, Role
from app.shared.ids import new_id

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

ME, COUNSELOR = new_id(), new_id()
SCOPES = frozenset(
    {
        "plans:read",
        "plans:write",
        "calendar:read",
        "calendar:write",
        "application:write",
    }
)
SECRET_TITLE = "Secret Summer Olympiad"
SECRET_URL = "https://olympiad.example.org/apply"
TOKEN = "tok_supersecret"
NOW = dt.datetime(2026, 11, 28, 9, tzinfo=dt.UTC)


async def _noop(*a: Any, **k: Any) -> None:  # noqa: ANN401
    return None


async def _ready(value: Any) -> Any:  # noqa: ANN401
    return value


def _entry() -> PersonalEntry:
    return PersonalEntry(
        id=new_id(),
        student_id=ME,
        kind="competition",
        title=SECRET_TITLE,
        provider="Org",
        url=SECRET_URL,
        summary=None,
        registration_deadline=dt.date(2027, 2, 1),
        starts_on=None,
        ends_on=None,
        planned_grade=None,
        planned_term=None,
        note=None,
        origin="mcp",
        dedup_key="k",
        created_at=NOW,
        updated_at=NOW,
    )


class Fixture:
    """Fakes of the admission services the plan tools call."""

    def __init__(self) -> None:  # noqa: C901 - one fake per service call
        self.calls: list[tuple[str, Any]] = []
        self.logged: list[Any] = []
        self.feed_active = False
        self.catalog_match: Any = None
        f = self

        async def resolve(actor: Actor) -> SimpleNamespace:
            student = actor.has(Role.STUDENT)
            return SimpleNamespace(
                user_id=actor.user_id,
                admission=SimpleNamespace(is_applicant=student, is_staff=not student),
            )

        async def add(ctx: Any, draft: Any, **kw: Any) -> PersonalAdded:  # noqa: ANN401
            f.calls.append(("add", (draft, kw)))
            if f.catalog_match:
                return PersonalAdded(planned_opportunity_id=f.catalog_match)
            return PersonalAdded(entry=_entry())

        async def delete(ctx: Any, entry_id: Any) -> None:  # noqa: ANN401
            f.calls.append(("delete", entry_id))

        async def proposals(entries: Any) -> dict[Any, Any]:  # noqa: ANN401
            return {}

        async def feed_status(ctx: Any) -> FeedStatus:  # noqa: ANN401
            return FeedStatus(f.feed_active, NOW if f.feed_active else None, (7,), (7,))

        async def issue_feed(ctx: Any, locale: str) -> IssuedFeed:  # noqa: ANN401
            f.calls.append(("issue_feed", locale))
            path = f"/v1/admission/calendar/{TOKEN}.ics"
            return IssuedFeed(TOKEN, path, await feed_status(ctx))

        async def revoke_feed(ctx: Any) -> None:  # noqa: ANN401
            f.calls.append(("revoke_feed", None))

        async def entries(*_a: Any) -> list[Any]:  # noqa: ANN401
            return [
                CalendarEntry(
                    key="personal:x:registration",
                    source="personal",
                    title=SECRET_TITLE,
                    day=dt.date(2027, 2, 1),
                    due_utc=NOW,
                ),
                CalendarEntry(
                    key="exam:sat",
                    source="exam",
                    title="SAT",
                    day=dt.date(2027, 3, 1),
                    due_utc=NOW,
                ),
            ]

        async def export(ctx: Any, locale: str, **kw: Any) -> str:  # noqa: ANN401
            f.calls.append(("export", kw))
            return "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

        async def active_feed(_user: Any) -> None:  # noqa: ANN401
            return None

        async def link_existing(ctx: Any, item_id: Any, opp_id: Any) -> Any:  # noqa
            f.calls.append(("link", (item_id, opp_id)))
            return SimpleNamespace(
                item_id=item_id, status="verified", opportunity_id=opp_id
            )

        async def record(*a: Any, **k: Any) -> None:  # noqa: ANN401
            f.logged.append((a, k))

        admission = SimpleNamespace(
            actor=SimpleNamespace(execute=resolve),
            personal_entries=SimpleNamespace(
                add=add, delete=delete, proposals=proposals
            ),
            calendar=SimpleNamespace(
                feed_status=feed_status,
                issue_feed=issue_feed,
                revoke_feed=revoke_feed,
                entries=entries,
                export=export,
                store=SimpleNamespace(active_feed=active_feed),
            ),
            item_opportunity=SimpleNamespace(link_existing=link_existing),
        )
        deps = SimpleNamespace(
            t=lambda key, **p: key,
            maintenance=None,
            rate_limiter=SimpleNamespace(hit=_noop),
            consent=None,
            scope_overlay=None,
            limits=SimpleNamespace(
                ai_access=lambda _u: _ready(SimpleNamespace(blocks=lambda _s: False))
            ),
            audit=SimpleNamespace(audit=_noop),
            call_log=SimpleNamespace(record=record),
            admission=admission,
            settings=SimpleNamespace(urls=SimpleNamespace(api="https://api.test/")),
        )
        self.mcp = FastMCP("t")
        kit = ToolKit(
            self.mcp,
            cast(McpDeps, deps),
            ToolGuard(cast(McpDeps, deps), "admission"),
        )
        for module in (plans, personal_plan, calendar, link_activity):
            module.register(kit)
        self.actor = Actor(ME, frozenset({Role.STUDENT}), scopes=SCOPES)

    def tool(self, name: str) -> Any:  # noqa: ANN401
        return self.mcp._tool_manager.get_tool(name)

    async def call(self, tool: str, /, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        fn = cast(Callable[..., Awaitable[dict[str, Any]]], self.tool(tool).fn)
        with patch.object(guard_module, "_token_actor", lambda: self.actor):
            return await fn(**kwargs)


@pytest.fixture
def fx() -> Fixture:
    return Fixture()


def test_destructive_and_idempotent_annotations(fx: Fixture) -> None:
    for name in (
        "remove_external_opportunity",
        "replace_calendar_feed",
        "revoke_calendar_feed",
    ):
        assert fx.tool(name).annotations.destructiveHint is True
    for name in (
        "add_external_opportunity",
        "update_external_opportunity",
        "create_calendar_feed",
        "link_activity_opportunity",
    ):
        assert fx.tool(name).annotations.destructiveHint is False
    assert fx.tool("add_external_opportunity").annotations.idempotentHint is True
    assert fx.tool("link_activity_opportunity").annotations.idempotentHint is True


async def test_staff_token_is_refused_on_applicant_tools(fx: Fixture) -> None:
    fx.actor = Actor(COUNSELOR, frozenset({Role.COUNSELOR}), scopes=SCOPES)
    for name, args in (
        ("add_external_opportunity", {"kind": "competition", "title": "x"}),
        ("remove_external_opportunity", {"entry_id": new_id()}),
        ("get_calendar_feed", {}),
        ("create_calendar_feed", {}),
        ("export_calendar_ics", {"keys": ["exam:sat"]}),
        (
            "link_activity_opportunity",
            {"item_id": new_id(), "opportunity_id": new_id()},
        ),
    ):
        with pytest.raises(ToolError):
            await fx.call(name, **args)
    assert fx.calls == []


async def test_add_external_is_mcp_origin_untrusted_and_unlogged(fx: Fixture) -> None:
    out = await fx.call(
        "add_external_opportunity",
        kind="competition",
        title=SECRET_TITLE,
        url=SECRET_URL,
        propose_to_catalog=True,
    )
    [(name, (draft, kw))] = fx.calls
    assert name == "add" and kw == {"origin": "mcp", "propose": True}
    assert draft.title == SECRET_TITLE
    assert out["entry"]["verified"] is False
    assert "entry.title" in out["untrusted_fields"]
    assert fx.logged
    assert SECRET_TITLE not in repr(fx.logged)
    assert SECRET_URL not in repr(fx.logged)


async def test_add_external_matching_catalog_plans_the_catalog_entry(
    fx: Fixture,
) -> None:
    fx.catalog_match = new_id()
    out = await fx.call("add_external_opportunity", kind="course", title="Known")
    assert out == {
        "planned_opportunity_id": str(fx.catalog_match),
        "reason": "already_in_catalog",
    }


async def test_create_feed_with_a_live_feed_is_feed_exists(fx: Fixture) -> None:
    fx.feed_active = True
    with pytest.raises(ToolError) as caught:
        await fx.call("create_calendar_feed")
    assert "feed_exists" in str(caught.value)
    assert fx.calls == []
    out = await fx.call("replace_calendar_feed", locale="ru")
    assert out["https_url"] == f"https://api.test/v1/admission/calendar/{TOKEN}.ics"
    assert out["webcal_url"].startswith("webcal://api.test/")


async def test_create_feed_shows_url_once_and_never_logs_it(fx: Fixture) -> None:
    out = await fx.call("create_calendar_feed")
    assert TOKEN in out["https_url"]
    assert TOKEN not in repr(fx.logged)


async def test_get_calendar_feed_has_no_token(fx: Fixture) -> None:
    fx.feed_active = True
    out = await fx.call("get_calendar_feed")
    assert set(out) == {"active", "created_at", "alarm_days_before"}
    assert TOKEN not in repr(out)


async def test_get_calendar_filters_sources_and_marks_titles(fx: Fixture) -> None:
    out = await fx.call(
        "get_calendar",
        start=dt.date(2027, 1, 1),
        end=dt.date(2027, 6, 1),
        sources=["personal"],
    )
    [event] = out["events"]
    assert event["source"] == "personal" and event["untrusted"] is True
    assert event["uid"].endswith("@admission")
    assert out["untrusted_fields"] == ["events[].title"]


async def test_export_ics_passes_keys(fx: Fixture) -> None:
    out = await fx.call("export_calendar_ics", keys=["exam:sat"])
    assert out["content_type"] == "text/calendar"
    assert out["ics"].startswith("BEGIN:VCALENDAR")
    [(name, kw)] = fx.calls
    assert name == "export" and kw["keys"] == ("exam:sat",)


async def test_link_activity_uses_link_existing(fx: Fixture) -> None:
    item, opp = new_id(), new_id()
    out = await fx.call("link_activity_opportunity", item_id=item, opportunity_id=opp)
    assert out["status"] == "verified"
    assert fx.calls == [("link", (item, opp))]


async def test_remove_external_calls_delete(fx: Fixture) -> None:
    entry_id = new_id()
    await fx.call("remove_external_opportunity", entry_id=entry_id)
    assert fx.calls == [("delete", entry_id)]
