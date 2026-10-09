"""LMS-AI: the authoring writes of the course workspace (``LmsWorkspaceCommands``)."""

import json
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.views import CourseDraftView, StepDraftView
from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    CourseNotFoundError,
    CoursePermissionError,
    DraftConflictError,
    FileMissingError,
    PlanInvalidError,
    StepNotFoundError,
    TitleInvalidError,
)
from app.modules.lms.domain.step_content import TextBlock
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    cards_block,
    quiz_block,
    seed_published,
    single_question,
    step_row,
    text_block,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PLAN: list[dict[str, Any]] = [
    {
        "title": "Limits",
        "steps": [
            {"title": "Idea of a limit", "brief": "Goal: **feel** the limit."},
            {"title": "Rules", "brief": "Sum and product."},
        ],
    },
    {"title": "Derivatives", "steps": [{"title": "Definition"}]},
]


def _titles(draft: CourseDraftView) -> list[tuple[str, list[str]]]:
    return [(s.title, [st.title for st in s.steps]) for s in draft.outline]


def _texts(draft: StepDraftView) -> list[str]:
    return [b.markdown for b in draft.content.blocks if isinstance(b, TextBlock)]


# - - - apply_outline - - -


async def test_a_plan_creates_its_sections_and_steps_in_the_draft(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Everything lands in the draft in plan order; nothing is published."""
    owner = course.team.owner

    result = await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    draft = await services.get_course_draft.execute(owner, course.id)
    assert _titles(draft) == [
        ("Limits", ["Idea of a limit", "Rules"]),
        ("Derivatives", ["Definition"]),
    ]
    assert [s["title"] for s in result["created_sections"]] == ["Limits", "Derivatives"]
    assert [s["id"] for s in result["created_sections"]] == [
        s.id for s in draft.outline
    ]
    assert [(s["title"], s["section_id"]) for s in result["created_steps"]] == [
        ("Idea of a limit", draft.outline[0].id),
        ("Rules", draft.outline[0].id),
        ("Definition", draft.outline[1].id),
    ]
    assert [s["step_id"] for s in result["created_steps"]] == [
        str(st.step_id) for sec in draft.outline for st in sec.steps
    ]
    assert (result["existing_sections"], result["existing_steps"]) == (0, 0)
    assert draft.live_version is None
    json.dumps(result)


async def test_the_plan_in_the_result_lists_every_item_as_new_with_its_ids(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """`plan` mirrors the request: action `new` or `exists`, with the real ids."""
    owner = course.team.owner

    result = await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    draft = await services.get_course_draft.execute(owner, course.id)
    assert result["plan"] == [
        {
            "title": "Limits",
            "section_id": draft.outline[0].id,
            "action": "new",
            "steps": [
                {
                    "title": "Idea of a limit",
                    "step_id": str(draft.outline[0].steps[0].step_id),
                    "action": "new",
                },
                {
                    "title": "Rules",
                    "step_id": str(draft.outline[0].steps[1].step_id),
                    "action": "new",
                },
            ],
        },
        {
            "title": "Derivatives",
            "section_id": draft.outline[1].id,
            "action": "new",
            "steps": [
                {
                    "title": "Definition",
                    "step_id": str(draft.outline[1].steps[0].step_id),
                    "action": "new",
                }
            ],
        },
    ]
    assert result["draft_seq"] == draft.draft_seq


async def test_a_second_identical_call_creates_nothing_and_touches_nothing(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Idempotent: no new rows, no draft_seq or lock_version bump."""
    owner = course.team.owner
    first = await services.workspace_commands.apply_outline(owner, course.id, PLAN)
    before = await services.get_course_draft.execute(owner, course.id)

    second = await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    after = await services.get_course_draft.execute(owner, course.id)
    assert second["created_sections"] == [] and second["created_steps"] == []
    assert (second["existing_sections"], second["existing_steps"]) == (2, 3)
    assert [s["action"] for s in second["plan"]] == ["exists", "exists"]
    assert [
        (s["title"], s["step_id"]) for sec in second["plan"] for s in sec["steps"]
    ] == [(s["title"], s["step_id"]) for sec in first["plan"] for s in sec["steps"]]
    assert after == before
    assert second["draft_seq"] == first["draft_seq"] == after.draft_seq


async def test_only_what_is_missing_is_created_and_nothing_is_renamed_or_moved(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """An existing section keeps its place, title and steps; new steps go last."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "limits")
    await services.create_section.execute(owner, course.id, "Integrals")
    known = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="IDEA  of a   LIMIT"
    )

    result = await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    draft = await services.get_course_draft.execute(owner, course.id)
    assert _titles(draft) == [
        ("limits", ["IDEA  of a   LIMIT", "Rules"]),
        ("Integrals", []),
        ("Derivatives", ["Definition"]),
    ]
    assert draft.outline[0].id == section.id
    assert draft.outline[0].steps[0].step_id == known.step_id
    assert [s["title"] for s in result["created_sections"]] == ["Derivatives"]
    assert [s["title"] for s in result["created_steps"]] == ["Rules", "Definition"]
    assert (result["existing_sections"], result["existing_steps"]) == (1, 1)
    assert result["plan"][0]["section_id"] == section.id
    assert result["plan"][0]["steps"][0] == {
        "title": "Idea of a limit",
        "step_id": str(known.step_id),
        "action": "exists",
    }


async def test_titles_match_without_case_and_extra_spaces(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """`  LIMITS ` and `idea   of a limit` find the existing section and step."""
    owner = course.team.owner
    await services.workspace_commands.apply_outline(owner, course.id, PLAN)
    before = await services.get_course_draft.execute(owner, course.id)

    result = await services.workspace_commands.apply_outline(
        owner,
        course.id,
        [{"title": "  LIMITS ", "steps": [{"title": "idea   of a limit"}]}],
    )

    after = await services.get_course_draft.execute(owner, course.id)
    assert result["created_sections"] == [] and result["created_steps"] == []
    assert after == before


async def test_a_dry_run_changes_nothing_and_reports_the_same_plan(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The preview has the same plan as the real call, with no ids for new items."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    before = await services.get_course_draft.execute(owner, course.id)

    preview = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, dry_run=True, add_briefs=True
    )

    assert await services.get_course_draft.execute(owner, course.id) == before
    assert preview["created_sections"] == [] and preview["created_steps"] == []
    assert (preview["existing_sections"], preview["existing_steps"]) == (1, 0)
    assert preview["draft_seq"] == before.draft_seq
    assert [(s["action"], s["section_id"]) for s in preview["plan"]] == [
        ("exists", section.id),
        ("new", None),
    ]
    assert all(
        (st["action"], st["step_id"]) == ("new", None)
        for sec in preview["plan"]
        for st in sec["steps"]
    )

    real = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, add_briefs=True
    )

    def shape(result: dict[str, Any]) -> list[Any]:
        return [
            (s["title"], s["action"], [(t["title"], t["action"]) for t in s["steps"]])
            for s in result["plan"]
        ]

    assert shape(real) == shape(preview)


async def test_a_dry_run_of_a_plan_the_draft_already_has_is_all_exists(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """After applying, the preview of the same plan shows nothing to do."""
    owner = course.team.owner
    await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    preview = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, dry_run=True
    )

    assert (preview["existing_sections"], preview["existing_steps"]) == (2, 3)
    assert all(
        st["step_id"] is not None for sec in preview["plan"] for st in sec["steps"]
    )


async def test_with_briefs_a_new_step_starts_with_its_brief_as_a_text_block(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Only new steps get the brief; a step without a brief stays empty."""
    owner = course.team.owner

    result = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, add_briefs=True
    )

    steps = {
        s["title"]: await services.get_step_draft.execute(owner, UUID(s["step_id"]))
        for s in result["created_steps"]
    }
    idea = steps["Idea of a limit"]
    assert _texts(idea) == ["Goal: **feel** the limit."]
    assert idea.content.blocks[0].id and idea.content.blocks[0].type == "text"
    assert _texts(steps["Rules"]) == ["Sum and product."]
    assert steps["Definition"].content.blocks == []
    assert idea.lock_version == 0 and idea.status == "new"


async def test_without_briefs_new_steps_are_empty_and_existing_steps_stay_untouched(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """`add_briefs` never writes into a step that exists already."""
    owner = course.team.owner
    first = await services.workspace_commands.apply_outline(owner, course.id, PLAN)
    idea_id = UUID(first["created_steps"][0]["step_id"])
    await services.workspace_commands.replace_step(
        owner,
        idea_id,
        {"title": "Idea of a limit", "blocks": [text_block("Mine")]},
        0,
        via_ai=False,
    )

    await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, add_briefs=True
    )

    idea = await services.get_step_draft.execute(owner, idea_id)
    assert _texts(idea) == ["Mine"]
    rules = await services.get_step_draft.execute(
        owner, UUID(first["created_steps"][1]["step_id"])
    )
    assert rules.content.blocks == []


async def test_a_plan_bumps_the_draft_sequence_once_however_big_it_is(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """One transaction under the course lock: one pending-changes snapshot."""
    owner = course.team.owner
    before = await services.get_course_draft.execute(owner, course.id)

    result = await services.workspace_commands.apply_outline(owner, course.id, PLAN)

    after = await services.get_course_draft.execute(owner, course.id)
    assert after.draft_seq == before.draft_seq + 1 == result["draft_seq"]
    assert after.lock_version == before.lock_version + 1
    pending = await services.get_pending_changes.execute(owner, course.id)
    assert pending.draft_seq == after.draft_seq and len(pending.steps) == 3


async def test_created_steps_carry_the_ai_mark_in_the_editor_and_the_database(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """`via_ai` marks the steps "changed by AI" like MCP ones are marked."""
    owner = course.team.owner

    result = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, add_briefs=True
    )

    step_id = UUID(result["created_steps"][0]["step_id"])
    draft = await services.get_step_draft.execute(owner, step_id)
    row = await step_row(sessionmaker_in_tx, step_id)
    outline = await services.get_course_draft.execute(owner, course.id)
    pending = await services.get_pending_changes.execute(owner, course.id)
    assert draft.updated_via == "ai" and draft.updated_by is not None
    assert (row.created_via, row.draft_updated_via) == ("ai", "ai")
    assert {s.badge for sec in outline.outline for s in sec.steps} == {"ai"}
    assert all(s.via_ai and not s.via_mcp for s in pending.steps)


async def test_without_via_ai_the_steps_are_marked_as_made_in_the_editor(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The mark follows the flag."""
    owner = course.team.owner

    result = await services.workspace_commands.apply_outline(
        owner, course.id, PLAN, via_ai=False
    )

    draft = await services.get_step_draft.execute(
        owner, UUID(result["created_steps"][0]["step_id"])
    )
    assert draft.updated_via == "ui"
    outline = await services.get_course_draft.execute(owner, course.id)
    assert {s.badge for sec in outline.outline for s in sec.steps} == {"new"}


async def test_applying_a_plan_never_touches_the_published_course(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The live version keeps its steps; the new ones are pending additions."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)

    await services.workspace_commands.apply_outline(
        owner, course.id, [{"title": "Limits", "steps": [{"title": "New one"}]}]
    )

    version = await services.get_version.execute(owner, course.id, 1)
    assert [s.step_id for s in version.outline[0].steps] == [
        seeded.step_a.step_id,
        seeded.step_b.step_id,
    ]
    pending = await services.get_pending_changes.execute(owner, course.id)
    assert [(s.title, s.change) for s in pending.steps] == [("New one", "added")]


@pytest.mark.parametrize("who", ["tester", "reviewer", "outsider"])
async def test_applying_a_plan_needs_the_edit_permission(
    services: AuthoringServices, course: CourseFixture, who: str
) -> None:
    """`view_drafts` reads; only `edit` writes. A dry run is a write preview too."""
    actor: Actor = getattr(course.team, who)

    for dry_run in (False, True):
        with pytest.raises(CoursePermissionError):
            await services.workspace_commands.apply_outline(
                actor, course.id, PLAN, dry_run=dry_run
            )

    draft = await services.get_course_draft.execute(course.team.owner, course.id)
    assert draft.outline == []


async def test_a_teacher_with_edit_and_an_lms_admin_may_apply_a_plan(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Everybody who edits the course can."""
    for actor, title in ((course.team.teacher, "A"), (course.team.admin, "B")):
        result = await services.workspace_commands.apply_outline(
            actor, course.id, [{"title": title}]
        )
        assert [s["title"] for s in result["created_sections"]] == [title]


async def test_an_unknown_course_is_not_found(services: AuthoringServices) -> None:
    """No course, no plan."""
    actor = Actor(user_id=new_id(), roles=frozenset())

    with pytest.raises(CourseNotFoundError):
        await services.workspace_commands.apply_outline(actor, new_id(), PLAN)


async def test_the_limits_of_a_plan_are_enforced_before_anything_is_written(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """30 sections, 30 steps per section, 1..200 character titles, 20,000 briefs."""
    owner = course.team.owner
    commands = services.workspace_commands
    too_many_sections = [{"title": f"S{i}"} for i in range(31)]
    too_many_steps = [{"title": "S", "steps": [{"title": f"T{i}"} for i in range(31)]}]
    long_brief = [{"title": "S", "steps": [{"title": "T", "brief": "x" * 20_001}]}]

    bad_plans: list[list[dict[str, Any]]] = [
        too_many_sections,
        too_many_steps,
        long_brief,
        [],
        [{"steps": []}],
    ]
    for bad in bad_plans:
        with pytest.raises(PlanInvalidError):
            await commands.apply_outline(owner, course.id, bad)
    for title in ("", "  ", "x" * 201):
        with pytest.raises(TitleInvalidError):
            await commands.apply_outline(owner, course.id, [{"title": title}])
        with pytest.raises(TitleInvalidError):
            await commands.apply_outline(
                owner, course.id, [{"title": "S", "steps": [{"title": title}]}]
            )

    draft = await services.get_course_draft.execute(owner, course.id)
    assert draft.outline == [] and draft.draft_seq == 0


async def test_a_plan_at_the_limits_is_applied(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A section with 30 steps and a 20,000 character brief goes through."""
    owner = course.team.owner
    plan = [
        {
            "title": "Big",
            "steps": [
                {"title": f"T{i}", "brief": "x" * 20_000 if i == 0 else ""}
                for i in range(30)
            ],
        }
    ]

    result = await services.workspace_commands.apply_outline(
        owner, course.id, plan, add_briefs=True
    )

    assert len(result["created_steps"]) == 30
    first = await services.get_step_draft.execute(
        owner, UUID(result["created_steps"][0]["step_id"])
    )
    assert [len(t) for t in _texts(first)] == [20_000]


async def test_a_brief_that_links_a_missing_file_is_refused_and_writes_nothing(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A brief is step content: it passes the same file checks as any text."""
    owner = course.team.owner
    plan = [
        {
            "title": "S",
            "steps": [{"title": "T", "brief": f"![x](/files/{UUID(int=7)})"}],
        }
    ]

    with pytest.raises(FileMissingError):
        await services.workspace_commands.apply_outline(
            owner, course.id, plan, add_briefs=True
        )

    draft = await services.get_course_draft.execute(owner, course.id)
    assert draft.outline == []


# - - - replace_step - - -


async def _empty_step(services: AuthoringServices, course: CourseFixture) -> UUID:
    result = await services.workspace_commands.apply_outline(
        course.team.owner, course.id, [{"title": "S", "steps": [{"title": "Intro"}]}]
    )
    return UUID(result["created_steps"][0]["step_id"])


LESSON: dict[str, Any] = {
    "title": "Intro to limits",
    "blocks": [
        {"id": "", "type": "text", "markdown": "### Idea"},
        quiz_block(single_question()),
        cards_block(),
    ],
}


async def test_replace_step_stores_the_content_with_server_assigned_ids(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Empty ids become server ids; the result shows the stored blocks."""
    owner = course.team.owner
    step_id = await _empty_step(services, course)

    result = await services.workspace_commands.replace_step(owner, step_id, LESSON, 0)

    draft = await services.get_step_draft.execute(owner, step_id)
    assert result["step_id"] == str(step_id)
    assert result["lock_version"] == draft.lock_version == 1
    assert result["blocks"] == [b.model_dump(mode="json") for b in draft.content.blocks]
    assert draft.content.title == "Intro to limits"
    assert [b["type"] for b in result["blocks"]] == ["text", "test", "flashcards"]
    ids: list[str] = []
    block = result["blocks"][1]
    ids += [
        result["blocks"][0]["id"],
        block["id"],
        result["blocks"][2]["cards"][0]["id"],
    ]
    ids += [q["id"] for q in block["questions"]]
    ids += [o["id"] for q in block["questions"] for o in q["options"]]
    assert all(len(i) == 8 for i in ids) and len(set(ids)) == len(ids)
    json.dumps(result)


async def test_replace_step_marks_the_change_as_ai_unless_asked_otherwise(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """`via_ai` decides between "changed by AI" and a person's edit."""
    owner = course.team.owner
    step_id = await _empty_step(services, course)

    first = await services.workspace_commands.replace_step(owner, step_id, LESSON, 0)
    by_ai = await services.get_step_draft.execute(owner, step_id)
    await services.workspace_commands.replace_step(
        owner,
        step_id,
        {"title": "Intro", "blocks": []},
        first["lock_version"],
        via_ai=False,
    )
    by_person = await services.get_step_draft.execute(owner, step_id)

    assert by_ai.updated_via == "ai" and by_person.updated_via == "ui"


async def test_replace_step_keeps_the_ids_it_already_issued(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: sending the stored blocks back changes nothing and moves no ids."""
    owner = course.team.owner
    step_id = await _empty_step(services, course)
    first = await services.workspace_commands.replace_step(owner, step_id, LESSON, 0)
    edited = [dict(b) for b in first["blocks"]]
    edited[0]["markdown"] = "### Idea, revised"

    second = await services.workspace_commands.replace_step(
        owner,
        step_id,
        {"title": "Intro to limits", "blocks": edited},
        first["lock_version"],
    )

    assert second["lock_version"] == first["lock_version"] + 1
    assert [b["id"] for b in second["blocks"]] == [b["id"] for b in first["blocks"]]
    assert second["blocks"][1] == first["blocks"][1]
    assert second["blocks"][0]["markdown"] == "### Idea, revised"


async def test_replace_step_accepts_null_ids_and_drops_unknown_keys(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Model output is forgiving: `id: null` means no id, extra keys are ignored."""
    owner = course.team.owner
    step_id = await _empty_step(services, course)

    result = await services.workspace_commands.replace_step(
        owner,
        step_id,
        {
            "title": "T",
            "note": "ignored",
            "blocks": [{"id": None, "type": "text", "markdown": "x", "extra": 1}],
        },
        0,
    )

    assert len(result["blocks"][0]["id"]) == 8


async def test_a_stale_lock_version_conflicts_and_the_error_carries_the_current_one(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The caller retries with `params.lock_version` after re-reading the step."""
    owner, teacher = course.team.owner, course.team.teacher
    step_id = await _empty_step(services, course)
    await services.workspace_commands.replace_step(
        teacher,
        step_id,
        {"title": "Intro", "blocks": [text_block("By a teacher")]},
        0,
        via_ai=False,
    )

    with pytest.raises(DraftConflictError) as caught:
        await services.workspace_commands.replace_step(owner, step_id, LESSON, 0)

    params = caught.value.params
    assert params["lock_version"] == 1
    assert params["theirs"]["lock_version"] == 1
    assert params["theirs"]["content"]["blocks"][0]["markdown"] == "By a teacher"
    unchanged = await services.get_step_draft.execute(owner, step_id)
    assert _texts(unchanged) == ["By a teacher"]
    retried = await services.workspace_commands.replace_step(
        owner, step_id, LESSON, params["lock_version"]
    )
    assert retried["lock_version"] == 2


@pytest.mark.parametrize(
    "content",
    [
        {"blocks": []},
        {"title": "T", "blocks": [{"type": "video", "url": "x"}]},
        {"title": "T", "blocks": [{"type": "text", "markdown": 5}]},
        {"title": "T", "blocks": "no"},
        {
            "title": "T",
            "blocks": [
                {"id": "dup", "type": "text", "markdown": "a"},
                {"id": "dup", "type": "text", "markdown": "b"},
            ],
        },
    ],
)
async def test_invalid_content_is_a_typed_error_and_changes_nothing(
    services: AuthoringServices, course: CourseFixture, content: dict[str, Any]
) -> None:
    """The model gets `lms/content-invalid`, not a corrupted draft."""
    owner = course.team.owner
    step_id = await _empty_step(services, course)

    with pytest.raises(ContentInvalidError):
        await services.workspace_commands.replace_step(owner, step_id, content, 0)

    draft = await services.get_step_draft.execute(owner, step_id)
    assert (draft.lock_version, draft.content.blocks) == (0, [])


@pytest.mark.parametrize("who", ["tester", "reviewer", "outsider"])
async def test_replace_step_needs_the_edit_permission(
    services: AuthoringServices, course: CourseFixture, who: str
) -> None:
    """Reading drafts is not enough to replace one."""
    step_id = await _empty_step(services, course)

    with pytest.raises(CoursePermissionError):
        await services.workspace_commands.replace_step(
            getattr(course.team, who), step_id, LESSON, 0
        )

    draft = await services.get_step_draft.execute(course.team.owner, step_id)
    assert draft.content.blocks == []


async def test_replace_step_of_an_unknown_step_is_not_found(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """No step, no write."""
    with pytest.raises(StepNotFoundError):
        await services.workspace_commands.replace_step(
            course.team.owner, new_id(), LESSON, 0
        )
