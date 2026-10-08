"""LMS-14, LMS-17: the live manifest, the render cache and what students never get."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import attempt_view
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.live import (
    RenderCache,
    changes_between,
    parse_manifest,
    render_revision,
)
from app.modules.lms.domain.learning.variant import build_variant, max_score_of
from app.shared.ids import new_id
from tests.lms.learning.builders import (
    cards,
    choice,
    content,
    number_question,
    quiz,
    text_block,
    text_question,
)
from tests.lms.learning.helpers import FORBIDDEN_KEYS, keys_of

import pytest


def manifest(*entries: tuple[UUID, UUID]) -> dict:
    """A stored manifest with one section of (step, revision) pairs."""
    return {
        "sections": [
            {
                "id": "s",
                "title": "Section",
                "steps": [
                    {"step_id": str(step), "revision_id": str(rev), "title": "T"}
                    for step, rev in entries
                ],
            }
        ]
    }


def test_the_manifest_reads_both_stored_shapes() -> None:
    """README → Course versioning: sections wrapped in an object or a bare list."""
    step, revision = new_id(), new_id()
    wrapped = parse_manifest(manifest((step, revision)))
    bare = parse_manifest(manifest((step, revision))["sections"])

    assert wrapped == bare
    assert wrapped.step_ids() == [step]
    assert wrapped.find(step).revision_id == revision
    assert wrapped.find(new_id()) is None


def test_changes_between_two_versions_name_new_and_changed_steps() -> None:
    """UF-LMS-05: the course page marks new and changed steps."""
    kept, edited, added = new_id(), new_id(), new_id()
    old_edit, new_edit = new_id(), new_id()
    shared = new_id()
    old = parse_manifest(manifest((kept, shared), (edited, old_edit)))
    new = parse_manifest(
        manifest((kept, shared), (edited, new_edit), (added, new_id()))
    )

    assert changes_between(old, new) == {edited: "changed", added: "new"}


def test_the_render_cache_drops_the_least_recently_used_revision() -> None:
    """Design: an in-process LRU keyed by revision id."""
    cache = RenderCache(capacity=2)
    items = [
        render_revision(new_id(), content(f"S{i}", text_block())) for i in range(3)
    ]

    cache.put(items[0])
    cache.put(items[1])
    assert cache.get(items[0].revision_id) is items[0]
    cache.put(items[2])

    assert cache.get(items[1].revision_id) is None
    assert cache.get(items[0].revision_id) is items[0]
    assert len(cache) == 2


def test_the_render_lists_tests_and_cards_without_any_answer_data() -> None:
    """LMS-17: correct answers never reach the browser in the step render."""
    body = content(
        "Step",
        text_block(),
        quiz(
            "quiz",
            [
                choice("q1", correct=["a"]),
                text_question("q2", accepted=["secret"], regex="s.*"),
                number_question("q3", value=42, tolerance=1),
            ],
        ),
        cards("cards", 2),
    )

    rendered = render_revision(new_id(), body)

    assert rendered.test_block_ids == ("quiz",)
    assert dict(rendered.card_ids) == {"cards": ("c1", "c2")}
    assert not FORBIDDEN_KEYS & keys_of(list(rendered.blocks))
    assert "secret" not in str(rendered.blocks)


@pytest.mark.parametrize("shuffle", [False, True])
def test_the_attempt_view_never_contains_correctness_data(shuffle: bool) -> None:
    """LMS-17: questions of an attempt carry only prompts, points and options."""
    test = quiz(
        "quiz",
        [
            choice("q1", correct=["a"]),
            text_question("q2", accepted=["secret"]),
            number_question("q3", value=42),
        ],
        shuffle_questions=shuffle,
        shuffle_options=shuffle,
    )
    attempt_id = new_id()
    variant = build_variant(test, attempt_id)
    attempt = Attempt(
        id=attempt_id,
        user_id=new_id(),
        step_id=new_id(),
        revision_id=new_id(),
        block_id="quiz",
        attempt_no=1,
        is_preview=False,
        variant=variant,
        started_at=datetime(2026, 10, 6, tzinfo=UTC),
        deadline_at=None,
        max_score=max_score_of(test, variant),
    )

    view = attempt_view(attempt, test).model_dump(mode="json")

    assert not FORBIDDEN_KEYS & keys_of(view)
    assert "secret" not in str(view)
    assert {q["id"] for q in view["questions"]} == {"q1", "q2", "q3"}
