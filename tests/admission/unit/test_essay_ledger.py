"""Group labels, due dates and match slot state of the essay ledger."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.modules.admission.application.essay_due import (
    DueDate,
    application_dues,
    earliest,
)
from app.modules.admission.application.essay_group_labels import GroupLabeler
from app.modules.admission.domain.chooser import ListEntry
from app.modules.admission.domain.documents import Milestone
from app.modules.admission.domain.essay_flow import (
    GroupLabel,
    PromptRef,
    build_map,
    fallback_label,
    practice_streak,
    prompt_key,
)
from app.modules.admission.domain.essays import Essay
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.shared.ids import new_id
from tests.admission.unit.test_essay_match import UNI, Bench
from tests.admission.unit.test_items_service import STUDENT

UTC = dt.UTC
PROMPT = "Describe a place where you are perfectly content, and why. Be brief."


class LabelRepo:
    def __init__(self) -> None:
        self.rows: dict[str, GroupLabel] = {}

    async def get_many(self, hashes: list[str]) -> dict[str, GroupLabel]:
        return {h: self.rows[h] for h in hashes if h in self.rows}

    async def put_many(self, labels: list[GroupLabel]) -> None:
        self.rows.update({g.members_hash: g for g in labels})


class Ai:
    def __init__(self, reply: dict[str, Any] | None) -> None:
        self.reply = reply
        self.calls = 0

    async def json(self, **_: Any) -> tuple[dict[str, Any], str]:
        self.calls += 1
        if self.reply is None:
            raise ConnectionError("model unreachable")
        return self.reply, "m"


def _labeler(ai: Ai) -> tuple[GroupLabeler, LabelRepo]:
    repo = LabelRepo()

    class Uow:
        group_labels = repo

        async def __aenter__(self) -> "Uow":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    return GroupLabeler(Uow, ai, BuiltinPrompts()), repo  # type: ignore[arg-type]


def _group() -> Any:
    inst = new_id()
    ref = PromptRef(prompt_key(inst, 0), inst, "U", 0, PROMPT, 250)
    return build_map([ref], None, model="none").groups[0]


async def test_labeler_falls_back_when_model_unreachable_and_stores_nothing() -> None:
    ai = Ai(None)
    labeler, repo = _labeler(ai)
    group = _group()
    assert await labeler.labels([group]) == {}
    assert repo.rows == {} and ai.calls == 1
    assert fallback_label(group.prompts) == "Describe a place where you are"
    await labeler.labels([group])
    assert ai.calls == 2  # not cached: tries again


async def test_labeler_stores_generated_label_once() -> None:
    group = _group()
    reply = {
        "labels": [{"key": group.key, "en": "Happy place", "ru": "Место", "uz": ""}]
    }
    ai = Ai(reply)
    labeler, repo = _labeler(ai)
    got = (await labeler.labels([group]))[group.key]
    assert (got.of("en"), got.of("ru")) == ("Happy place", "Место")
    assert got.of("uz") == "Место" and len(repo.rows) == 1
    await labeler.labels([group])
    assert ai.calls == 1


def _due_uow(entries: list[ListEntry], ms: list[Milestone]) -> Any:
    async def listed(_: Any) -> list[ListEntry]:
        return entries

    async def miles(ids: Any) -> list[Milestone]:
        return [m for m in ms if m.list_entry_id in ids]

    return SimpleNamespace(
        shortlist=SimpleNamespace(entries=listed),
        deadlines=SimpleNamespace(milestones_of_entries=miles),
    )


def d(day: int) -> dt.datetime:
    return dt.datetime(2026, 12, day, tzinfo=UTC)


async def test_due_is_earliest_application_milestone() -> None:
    inst = new_id()
    entry = ListEntry(new_id(), STUDENT, inst)
    ms = [
        Milestone(new_id(), entry.id, "application", d(20), predicted=True),
        Milestone(new_id(), entry.id, "application", d(5)),
        Milestone(new_id(), entry.id, "application", None),
        Milestone(new_id(), entry.id, "decision", d(1)),
    ]
    got = await application_dues(_due_uow([entry], ms), STUDENT)
    assert got == {inst: DueDate(d(5), False)}
    assert earliest([]) is None
    assert earliest([DueDate(d(9), True), DueDate(d(3), False)]) == DueDate(d(3), False)


def test_practice_streak_today_or_yesterday_rule() -> None:
    today = dt.date(2026, 11, 21)
    one = dt.timedelta(days=1)
    assert practice_streak([], today) == 0
    assert practice_streak([today, today - one, today - 3 * one], today) == 2
    assert practice_streak([today - one, today - 2 * one], today) == 2
    assert practice_streak([today - 2 * one], today) == 0


async def test_match_slot_required_assigned_and_over_limit() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    long = await b.essay("supplemental", 200)
    await b.match.assign(ctx, UNI, "supp:1", long.id)  # limit 150
    t = await b.match.table(ctx, UNI)
    by = {s.slot: s for s in t.slots}
    assert by["supp:0"].assigned is None
    a = by["supp:1"].assigned
    assert a is not None and a.over_limit and a.essay_id == long.id
    assert a.word_count == 200 and a.title == long.title
    assert all(s.required for s in t.slots)
    fits = Essay(new_id(), STUDENT, kind="supplemental", title="s", body="w " * 10)
    await b.repo.add(fits)
    t = await b.match.assign(ctx, UNI, "supp:0", fits.id)  # limit 250
    got = next(s.assigned for s in t.slots if s.slot == "supp:0")
    assert got is not None and not got.over_limit
