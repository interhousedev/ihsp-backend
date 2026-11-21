"""Honor suggestions from certificates and the standard-exam merge of /tests/."""

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.admission.application.honor_suggestions import (
    HonorSuggestionService,
)
from app.modules.admission.application.items import ItemService
from app.modules.admission.application.score_certificates import merge_certificates
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.items import Item
from app.shared.contracts.certificates import StudentCertificate
from app.shared.ids import new_id
from tests.admission.unit.score_defs import SAT
from tests.admission.unit.test_items_service import STUDENT, ItemsUow, World

import pytest

D = dt.date(2026, 5, 1)


def cert(code: str, standard: bool, **values: Any) -> StudentCertificate:
    return StudentCertificate(
        new_id(),
        code,
        {"uz": code, "ru": code, "en": code.title()},
        standard,
        "olympiad" if not standard else "academic",
        D,
        None,
        values,
    )


class Certs:
    def __init__(self, *rows: StudentCertificate) -> None:
        self.rows = list(rows)

    async def for_student(self, student_id: UUID) -> list[StudentCertificate]:
        return self.rows


def services(w: World, certs: Certs) -> tuple[ItemService, HonorSuggestionService]:
    uow = lambda: ItemsUow(w.store, w.data)  # noqa: E731
    return (
        ItemService(uow, w.policy, certs),
        HonorSuggestionService(uow, w.policy, certs),
    )


async def test_suggest_dismiss_and_link() -> None:
    w = World()
    olympiad = cert("olympiad", False, level="Republican", subject="Math")
    sat = cert("sat", True, score=1500)
    items, sugg = services(w, Certs(olympiad, sat))
    ctx = await w.ctx()
    got = await sugg.suggestions(ctx, "en")
    assert [s.entry_id for s in got.suggested] == [olympiad.entry_id]
    first = got.suggested[0]
    assert (first.title, first.level, first.category) == (
        "Olympiad: Math",
        "national",
        "olympiad",
    )
    await sugg.dismiss(ctx, olympiad.entry_id)
    got = await sugg.suggestions(ctx, "en")
    assert got.suggested == []
    assert [s.dismissed for s in got.available] == [True]
    with pytest.raises(AdmissionNotFoundError):
        await sugg.dismiss(ctx, sat.entry_id)
    honor = Item(
        new_id(),
        STUDENT,
        "honor",
        first.title,
        category=first.category,
        level=first.level,
        certificate_entry_id=olympiad.entry_id,
    )
    await items.create(ctx, honor)
    assert (await sugg.suggestions(ctx, "en")).available == []
    with pytest.raises(AdmissionConflictError):
        await items.create(ctx, honor)


async def test_link_to_foreign_certificate_is_not_found() -> None:
    w = World()
    items, _ = services(w, Certs())
    bad = Item(
        new_id(), STUDENT, "honor", "X", certificate_entry_id=new_id(), category="other"
    )
    with pytest.raises(AdmissionNotFoundError):
        await items.create(await w.ctx(), bad)


def test_merge_adds_standard_scores_without_duplicates() -> None:
    test = SAT
    c = cert("sat", True, score=1500)
    other = cert("toefl", True, score=100)
    merged, exams = merge_certificates(
        STUDENT,
        [],
        [test],
        [c, other, cert("olympiad", False)],
        dt.datetime.now(dt.UTC),
    )
    assert [e.total for e in merged] == [Decimal(1500)]
    assert merged[0].source == "certificate"
    assert [x.type_code for x in exams] == ["toefl"]
    again, _ = merge_certificates(
        STUDENT,
        merged[:1]
        and [
            merged[0].__class__(**{**_d(merged[0]), "source": "manual", "id": new_id()})
        ],
        [test],
        [c],
        dt.datetime.now(dt.UTC),
    )
    assert len(again) == 1


def _d(e: Any) -> dict[str, Any]:
    return {f: getattr(e, f) for f in e.__slots__}
