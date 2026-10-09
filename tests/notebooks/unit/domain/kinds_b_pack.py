"""A two-source context pack for the quiz, table, slides and infographic tests."""

from app.modules.notebooks.domain.context import ContextPack
from tests.notebooks.unit.domain.pack_builder import make_pack


def two_source_pack() -> ContextPack:
    """Sources "Biology 10.pdf" (S1) and "Lesson notes" (S2) with three passages each.

    Labels ``S1:P1`` to ``S1:P3`` and ``S2:P1`` to ``S2:P3``; the page of a passage is
    its number.
    """
    return make_pack(
        [
            [
                "Light reactions split water and release oxygen.",
                "The Calvin cycle fixes carbon dioxide into sugar.",
                "Chlorophyll absorbs light in the thylakoids.",
            ],
            [
                "Notes on stomata and gas exchange.",
                "Notes on roots and water uptake.",
                "Notes on leaves and veins.",
            ],
        ],
        titles=["Biology 10.pdf", "Lesson notes"],
    )
