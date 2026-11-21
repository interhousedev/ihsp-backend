"""Rating validation, the ratings-to-weights map and profession picks."""

from app.modules.admission.domain.errors import (
    CharLimitError,
    InvalidAnswerError,
    ItemLimitError,
)
from app.modules.admission.domain.fit import weights_of
from app.modules.admission.domain.fit_ratings import clean_ratings
from app.modules.admission.domain.professions import clean_chips, clean_choice
from app.modules.admission.infrastructure.professions_catalog import (
    JsonProfessionCatalog,
)

import pytest


def test_weights_follow_the_documented_mapping() -> None:
    w = weights_of(
        {
            "price": 10,
            "salary": 5,
            "ai_resilience": 5,
            "prestige": 5,
            "academics": 5,
            "social": 5,
            "city": 5,
            "home": 5,
        }
    )
    assert w["afford"] == pytest.approx(10 / 45, abs=1e-3)
    assert w["goals"] == pytest.approx(10 / 45, abs=1e-3)
    assert w["traits"] == pytest.approx(15 / 45, abs=1e-3)
    assert sum(w.values()) == pytest.approx(1, abs=1e-3)


def test_ratings_default_and_bounds() -> None:
    assert clean_ratings({})["price"] == 5
    assert clean_ratings({"home": 10})["home"] == 10
    for bad in ({"price": 0}, {"price": 11}, {"colour": 5}):
        with pytest.raises(InvalidAnswerError):
            clean_ratings(bad)


def test_chips_and_choice_limits() -> None:
    assert clean_chips("love", [" chess ", "Chess", ""]) == ("chess",)
    with pytest.raises(CharLimitError):
        clean_chips("love", ["x" * 61])
    with pytest.raises(ItemLimitError):
        clean_chips("love", [str(i) for i in range(9)])
    known = {"1", "2", "3", "4", "5", "6"}
    assert [c.profession_id for c in clean_choice([("2", 2), ("1", 1)], known)] == [
        "1",
        "2",
    ]
    with pytest.raises(ItemLimitError):
        clean_choice([(str(i), i) for i in range(1, 7)], known)
    with pytest.raises(InvalidAnswerError):
        clean_choice([("1", 1), ("1", 2)], known)
    with pytest.raises(InvalidAnswerError):
        clean_choice([("9", 1)], known)


def test_catalog_loads_and_uz_falls_back_to_ru() -> None:
    cat = JsonProfessionCatalog()
    assert len(cat.all()) > 100
    p = cat.all()[0]
    assert cat.get(p.id) is p
    assert p.name("uz")
    assert p.matches(p.names["ru"][:4])
