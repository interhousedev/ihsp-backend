"""PLAN: a slide-by-slide outline is confirmed before the deck is generated."""

from app.modules.notebooks.domain.artifacts.kinds.slides import (
    SLIDE_COUNTS,
    SlidesHandler,
)
from app.modules.notebooks.domain.artifacts.slides_shape import TOLERANCE
from app.modules.notebooks.domain.presentation_plan import (
    PLAN_MAX_SLIDES,
    PlanSlide,
    clean_slides,
    length_for,
    outline_text,
    over_limit,
)


def _slides(count: int) -> list[PlanSlide]:
    return [PlanSlide(title=f"Slide {n}", bullets=["a", "b"]) for n in range(count)]


def test_the_limit_is_the_longest_deck() -> None:
    """PLAN: a plan may not ask for more slides than the longest deck allows."""
    assert PLAN_MAX_SLIDES == SLIDE_COUNTS["long"] + TOLERANCE
    assert not over_limit(_slides(PLAN_MAX_SLIDES))
    assert over_limit(_slides(PLAN_MAX_SLIDES + 1))


def test_the_length_fits_the_slide_count() -> None:
    """PLAN: the deck's length is the one whose range holds the plan."""
    assert length_for(5) == "short"
    assert length_for(8) == "short"
    assert length_for(10) == "default"
    assert length_for(12) == "default"
    assert length_for(13) == "long"
    assert length_for(18) == "long"


def test_clean_slides_trims_and_drops_empty_bullets() -> None:
    """PLAN: edits are stored clean: no blank bullets, spaces collapsed."""
    slides = clean_slides(
        [PlanSlide(title="  Intro   to cells ", bullets=["  one ", "", "   ", "two"])]
    )
    assert slides == [PlanSlide(title="Intro to cells", bullets=["one", "two"])]


def test_outline_text_is_numbered() -> None:
    """PLAN: the outline the deck follows lists every slide with its bullets."""
    text = outline_text(
        [
            PlanSlide(title="Cells", bullets=["Membrane", "Nucleus"]),
            PlanSlide(title="Summary", bullets=[]),
        ]
    )
    assert text.splitlines() == [
        "1. Cells",
        "   - Membrane",
        "   - Nucleus",
        "2. Summary",
    ]


def test_slides_task_follows_an_outline() -> None:
    """PLAN: a deck made from a plan gets the outline in its task block."""
    handler = SlidesHandler()
    options = handler.parse_options(
        {
            "length": "short",
            "outline": [{"title": "Photosynthesis", "bullets": ["Light", "Sugar"]}],
        }
    )
    task = handler.task_block(options, None)
    assert "1. Photosynthesis" in task
    assert "   - Light" in task
    assert handler.stored_options(options)["outline"][0]["title"] == "Photosynthesis"


def test_slides_without_outline_are_unchanged() -> None:
    """PLAN: a plain deck request has no outline block."""
    handler = SlidesHandler()
    options = handler.parse_options({})
    assert "Follow this outline" not in handler.task_block(options, None)
    assert "outline" not in handler.stored_options(options)
