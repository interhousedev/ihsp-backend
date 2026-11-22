"""Typed-in professions: ranked search, the filled card, persistence and picking."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.profession_fill import build_custom
from app.modules.admission.application.professions import ProfessionService
from app.modules.admission.domain.errors import (
    CharLimitError,
    InvalidAnswerError,
)
from app.modules.admission.domain.professions import (
    Profession,
    ProfessionPlan,
    clean_title,
)
from app.modules.admission.infrastructure.professions_catalog import (
    JsonProfessionCatalog,
)
from app.modules.ai.infrastructure.fake_career import build_career_document
from app.shared.ids import new_id

import pytest

USER = new_id()
CTX: Any = SimpleNamespace(user_id=USER)
CATALOG = JsonProfessionCatalog()


def _p(**kw: Any) -> Profession:
    base: dict[str, Any] = {
        "id": "2512",
        "group": "2",
        "names": {"en": "Software developer", "ru": "Разработчик", "uz": "Dasturchi"},
        "ai_exposure": 0.5,
        "ai_risk": "medium",
        "horizon": "5y",
        "related_fields": ("computer_science",),
    }
    return Profession(**{**base, **kw})


def test_rank_orders_names_before_fields_before_description() -> None:
    by_name = _p()
    by_field = _p(id="1", names={"en": "Analyst"}, related_fields=("computer_science",))
    by_text = _p(id="2", names={"en": "Tutor"}, descriptions={"en": "teaches software"})
    assert by_name.rank("software") == 1
    assert by_field.rank("computer") == 2
    assert by_text.rank("software") == 3
    assert by_name.rank("2512") == 0
    assert by_name.rank("zzz") is None
    assert by_name.rank("software разработчик") == 1


def test_rank_finds_group_names_and_tags() -> None:
    p = _p(tags=("coding",))
    assert p.rank("coding") == 2
    assert p.rank("professionals") == 2


def test_search_puts_name_matches_first() -> None:
    svc = ProfessionService(lambda: None, CATALOG)  # type: ignore[arg-type]
    found = svc.search("engineer", 100)
    assert found
    ranks = [p.rank("engineer") for p in found]
    assert ranks == sorted(r for r in ranks if r is not None)
    assert ranks[0] == 1


def test_clean_title() -> None:
    assert clean_title("  Solution   Architect ") == "Solution Architect"
    with pytest.raises(InvalidAnswerError):
        clean_title("   ")
    with pytest.raises(CharLimitError):
        clean_title("x" * 81)


def _fill_doc(**kw: Any) -> dict[str, Any]:
    doc = build_career_document(
        "career_profession_fill",
        [{"role": "user", "content": "[title] Solution Architect"}],
    )
    assert doc is not None
    return {**doc, **kw}


def test_build_custom_keeps_catalogue_vocabulary_and_clamps() -> None:
    card = build_custom(
        _fill_doc(isco_id="9999", related_fields=["law", "nonsense"], ai_exposure=3),
        "Solution Architect",
        CATALOG,
    )
    assert card.custom and card.id.startswith("c-")
    assert card.related_fields == ("law",)
    assert card.ai_exposure == 0.7 and card.ai_risk == "high"
    assert card.isco_id is None and card.group == "2"
    assert card.names["en"] == "Solution Architect"


def test_build_custom_takes_exposure_from_the_isco_entry() -> None:
    card = build_custom(_fill_doc(isco_id="2512"), "Solution Architect", CATALOG)
    known = CATALOG.get("2512")
    assert known is not None
    assert card.isco_id == "2512" and card.ai_exposure == known.ai_exposure


class Plans:
    def __init__(self) -> None:
        self.plan = ProfessionPlan(USER)

    async def get(self, student_id: UUID) -> ProfessionPlan:
        return self.plan

    async def save_chosen(self, student_id: UUID, chosen: Any) -> None:
        self.plan = ProfessionPlan(
            student_id, chosen, self.plan.ikigai, self.plan.custom
        )

    async def save_custom(self, student_id: UUID, custom: Any) -> None:
        self.plan = ProfessionPlan(
            student_id, self.plan.chosen, self.plan.ikigai, custom
        )


class Uow:
    def __init__(self, plans: Plans) -> None:
        self.profession_plans = plans

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _service() -> tuple[ProfessionService, Plans, list[str]]:
    plans, asked = Plans(), []

    async def filler(ctx: Any, title: str, locale: str) -> Profession:
        asked.append(title)
        return build_custom(_fill_doc(), title, CATALOG)

    svc = ProfessionService(
        lambda: Uow(plans), CATALOG, filler  # type: ignore[arg-type, return-value]
    )
    return svc, plans, asked


async def test_fill_stores_card_and_it_can_be_picked_with_catalogue_ids() -> None:
    svc, plans, asked = _service()
    card = await svc.fill(CTX, "Solution Architect", "en")
    again = await svc.fill(CTX, " solution architect ", "en")
    assert again.id == card.id and asked == ["Solution Architect"]
    rows = await svc.choose(CTX, [("2512", 1), (card.id, 2)])
    assert [r.profession.id for r in rows] == ["2512", card.id]
    assert rows[1].profession.custom
    assert [p.id for p in plans.plan.custom] == [card.id]


async def test_unpicked_custom_cards_are_dropped_and_unknown_ids_refused() -> None:
    svc, plans, _ = _service()
    card = await svc.fill(CTX, "Solution Architect", "en")
    with pytest.raises(InvalidAnswerError):
        await svc.choose(CTX, [("c-unknown", 1)])
    await svc.choose(CTX, [("2512", 1)])
    assert plans.plan.custom == ()
    with pytest.raises(InvalidAnswerError):
        await svc.choose(CTX, [(card.id, 1)])


async def test_picks_stay_capped_at_five_with_customs() -> None:
    svc, _, _ = _service()
    card = await svc.fill(CTX, "Solution Architect", "en")
    ids = [p.id for p in CATALOG.all()[:5]]
    from app.modules.admission.domain.errors import ItemLimitError

    with pytest.raises(ItemLimitError):
        await svc.choose(CTX, [(i, n + 1) for n, i in enumerate([*ids, card.id])])
