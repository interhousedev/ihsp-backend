"""LMS-6, LMS-7, LMS-13, LMS-23, UF-LMS-08: editing in a draft."""

from collections.abc import Callable
from uuid import UUID, uuid4

from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    CoursePermissionError,
    DraftConflictError,
    FileMissingError,
    OutlineError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.outline import (
    AddSection,
    MoveStep,
    RemoveStep,
    RenameSection,
)
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor
from tests.fakes.lms.files import FakeFilesApi
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import (
    content_of,
    quiz_block,
    seed_published,
    set_blocks,
    single_question,
    step_row,
    text_block,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_meta_is_saved_in_the_draft_and_not_in_the_live_course(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-6: save stores changes without showing them to students."""
    owner = course.team.owner

    saved = await services.update_course_meta.execute(
        owner, course.id, title="Calculus 2", description="New text", lock_version=0
    )

    assert (saved.title, saved.description) == ("Calculus 2", "New text")
    assert saved.lock_version == 1
    assert saved.draft_seq == 1
    assert saved.live_version is None


async def test_meta_save_with_a_stale_lock_version_conflicts_and_shows_theirs(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-13: the second save is refused with the current draft."""
    owner, teacher = course.team.owner, course.team.teacher
    await services.update_course_meta.execute(
        owner, course.id, title="Mine", description="", lock_version=0
    )

    with pytest.raises(DraftConflictError) as caught:
        await services.update_course_meta.execute(
            teacher, course.id, title="Theirs", description="", lock_version=0
        )

    assert caught.value.code == "common/conflict"
    assert caught.value.status == 409
    theirs = caught.value.params["theirs"]
    assert theirs["title"] == "Mine"
    assert theirs["lock_version"] == 1


async def test_two_outline_edits_with_the_same_lock_version_one_conflicts(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-13: outline operations are checked against the lock version."""
    owner, teacher = course.team.owner, course.team.teacher
    first = await services.apply_outline_ops.execute(
        owner, course.id, [AddSection(op="add_section", title="A")], lock_version=0
    )

    with pytest.raises(DraftConflictError) as caught:
        await services.apply_outline_ops.execute(
            teacher,
            course.id,
            [AddSection(op="add_section", title="B")],
            lock_version=0,
        )

    assert first.lock_version == 1
    assert [s.title for s in first.outline] == ["A"]
    assert caught.value.params["theirs"]["lock_version"] == 1
    retried = await services.apply_outline_ops.execute(
        teacher, course.id, [AddSection(op="add_section", title="B")], lock_version=1
    )
    assert [s.title for s in retried.outline] == ["A", "B"]


async def test_outline_operations_rename_move_and_remove(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-08 2: sections and steps are reordered with operations."""
    owner = course.team.owner
    s1 = await services.create_section.execute(owner, course.id, "Limits")
    s2 = await services.create_section.execute(owner, course.id, "Derivatives")
    step = await services.create_step.execute(
        owner, course.id, section_id=s1.id, title="Intro"
    )

    moved = await services.apply_outline_ops.execute(
        owner,
        course.id,
        [
            RenameSection(op="rename_section", section_id=s1.id, title="Limits I"),
            MoveStep(
                op="move_step", step_id=step.step_id, to_section_id=s2.id, position=0
            ),
        ],
        lock_version=None,
    )
    removed = await services.apply_outline_ops.execute(
        owner,
        course.id,
        [RemoveStep(op="remove_step", step_id=step.step_id)],
        lock_version=None,
    )

    assert [(s.title, len(s.steps)) for s in moved.outline] == [
        ("Limits I", 0),
        ("Derivatives", 1),
    ]
    assert moved.outline[1].steps[0].step_id == step.step_id
    assert all(not s.steps for s in removed.outline)


async def test_a_bad_outline_operation_is_a_typed_error_and_changes_nothing(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A failing operation aborts the whole request."""
    owner = course.team.owner
    await services.create_section.execute(owner, course.id, "Limits")
    before = await services.get_course_draft.execute(owner, course.id)

    with pytest.raises(OutlineError):
        await services.apply_outline_ops.execute(
            owner,
            course.id,
            [
                AddSection(op="add_section", title="Extra"),
                RenameSection(op="rename_section", section_id="nope", title="x"),
            ],
            lock_version=None,
        )

    after = await services.get_course_draft.execute(owner, course.id)
    assert after == before


async def test_new_step_lands_in_the_outline_with_a_new_badge(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-7: new steps are badged until they are published."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")

    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro", position=0
    )

    draft = await services.get_course_draft.execute(owner, course.id)
    assert step.status == "new"
    assert step.updated_via == "ui"
    assert step.content.title == "Intro" and step.content.blocks == []
    assert [(s.title, s.badge) for s in draft.outline[0].steps] == [("Intro", "new")]
    assert draft.pending_count == 1


async def test_creating_a_step_in_an_unknown_section_is_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The section must exist in the draft outline."""
    with pytest.raises(OutlineError):
        await services.create_step.execute(
            course.team.owner, course.id, section_id="nope", title="Intro"
        )


async def test_server_assigns_unique_ids_and_keeps_known_ones(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: the server assigns IDs and keeps them when the client sends them back."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )

    saved = await set_blocks(
        services,
        owner,
        step,
        text_block("A"),
        quiz_block(single_question()),
        text_block("B"),
    )
    again = await services.save_step_draft.execute(
        owner,
        step.step_id,
        saved.content.model_copy(update={"title": "Intro 2"}),
        saved.lock_version,
    )

    ids = [b.id for b in saved.content.blocks]
    test_block = saved.content.blocks[1]
    assert all(len(i) == 8 for i in ids) and len(set(ids)) == 3
    assert [b.id for b in again.content.blocks] == ids
    assert again.content.blocks[1].questions[0].id == test_block.questions[0].id


async def test_an_id_the_server_never_issued_is_replaced(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: clients cannot choose IDs."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    content = content_of("Intro", {"id": "mine", "type": "text", "markdown": "x"})

    saved = await services.save_step_draft.execute(
        owner, step.step_id, content, step.lock_version
    )

    assert saved.content.blocks[0].id not in ("", "mine")


async def test_duplicate_ids_inside_one_content_are_rejected(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: IDs are unique; duplicates are refused."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    saved = await set_blocks(services, owner, step, text_block("A"))
    known = saved.content.blocks[0].id
    duplicated = content_of(
        "Intro",
        {"id": known, "type": "text", "markdown": "A"},
        {"id": known, "type": "text", "markdown": "B"},
    )

    with pytest.raises(ContentInvalidError):
        await services.save_step_draft.execute(
            owner, step.step_id, duplicated, saved.lock_version
        )


async def test_an_id_from_an_old_revision_stays_valid_after_it_left_the_draft(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-23: IDs known from any revision of the step are kept (undo after delete)."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    published_block_id = seeded.step_a.content.blocks[0].id
    emptied = await set_blocks(services, owner, seeded.step_a)

    restored = await services.save_step_draft.execute(
        owner,
        seeded.step_a.step_id,
        content_of(
            "Step A", {"id": published_block_id, "type": "text", "markdown": "A1"}
        ),
        emptied.lock_version,
    )

    assert restored.content.blocks[0].id == published_block_id


async def test_step_save_with_a_stale_lock_version_conflicts_and_shows_theirs(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-13, UF-LMS-08 3a: the second save sees the other person's version."""
    owner, teacher = course.team.owner, course.team.teacher
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    mine = await set_blocks(services, owner, step, text_block("Mine"))

    with pytest.raises(DraftConflictError) as caught:
        await services.save_step_draft.execute(
            teacher,
            step.step_id,
            content_of("Intro", text_block("Theirs")),
            step.lock_version,
        )

    theirs = caught.value.params["theirs"]
    assert theirs["lock_version"] == mine.lock_version
    assert theirs["content"]["blocks"][0]["markdown"] == "Mine"
    assert theirs["updated_by"]["id"] == str(owner.user_id)
    unchanged = await services.get_step_draft.execute(owner, step.step_id)
    assert unchanged.content.blocks[0].markdown == "Mine"


async def test_saving_unchanged_content_writes_nothing(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Autosave every 30 seconds must not bump versions when nothing changed."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    saved = await set_blocks(services, owner, step, text_block("A"))
    seq = (await services.get_course_draft.execute(owner, course.id)).draft_seq

    again = await services.save_step_draft.execute(
        owner, step.step_id, saved.content, saved.lock_version
    )

    assert again.lock_version == saved.lock_version
    assert (await services.get_course_draft.execute(owner, course.id)).draft_seq == seq


async def test_every_step_save_bumps_the_course_draft_seq(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """spec: every save bumps `draft_seq`, which publishing checks."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    before = (await services.get_course_draft.execute(owner, course.id)).draft_seq

    await set_blocks(services, owner, step, text_block("A"))

    after = (await services.get_course_draft.execute(owner, course.id)).draft_seq
    assert after == before + 1


async def test_files_referenced_in_markdown_must_exist_and_are_tracked(
    services: AuthoringServices,
    course: CourseFixture,
    files: FakeFilesApi,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """spec: `file_ids` are the files used by the draft and must exist."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    picture = files.add_file()

    with pytest.raises(FileMissingError):
        await set_blocks(
            services, owner, step, text_block(f"![x](/files/{UUID(int=5)})")
        )
    saved = await set_blocks(
        services, owner, step, text_block(f"![x](/files/{picture.id})")
    )

    assert (await step_row(sessionmaker_in_tx, saved.step_id)).file_ids == [picture.id]


async def test_a_tester_reads_drafts_but_cannot_save_them(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-5: `view_drafts` is read-only."""
    owner, tester, reviewer = (
        course.team.owner,
        course.team.tester,
        course.team.reviewer,
    )
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )

    assert (
        await services.get_course_draft.execute(tester, course.id)
    ).slug == "calculus"
    assert (
        await services.get_step_draft.execute(tester, step.step_id)
    ).step_id == step.step_id
    with pytest.raises(CoursePermissionError):
        await set_blocks(services, tester, step, text_block("hack"))
    with pytest.raises(CoursePermissionError):
        await services.create_section.execute(tester, course.id, "Hack")
    with pytest.raises(CoursePermissionError):
        await services.get_step_draft.execute(reviewer, step.step_id)


async def test_the_invite_code_is_hidden_from_testers(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The code is for people who can edit or manage staff."""
    owner, tester = course.team.owner, course.team.tester
    await services.update_course_settings.execute(
        owner, course.id, visibility=Visibility.INVITE
    )

    assert (await services.get_course_draft.execute(owner, course.id)).invite_code
    assert (
        await services.get_course_draft.execute(tester, course.id)
    ).invite_code is None


async def test_unknown_and_foreign_steps_are_not_found(
    services: AuthoringServices, course: CourseFixture, make_actor: Callable[..., Actor]
) -> None:
    """A random step ID is a 404."""
    with pytest.raises(StepNotFoundError):
        await services.get_step_draft.execute(course.team.owner, uuid4())


async def test_oversized_content_is_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A step is 5-20 KB; a megabyte of Markdown is refused, not stored."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )

    with pytest.raises(ContentInvalidError) as caught:
        await set_blocks(services, owner, step, text_block("x" * 1_100_000))

    assert caught.value.params["reason"] == "too-large"


async def test_continuous_autosaves_update_one_draft_in_place(
    services: AuthoringServices,
    course: CourseFixture,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Autosave every second or two: one draft per step, one pending entry."""
    owner = course.team.owner
    section = await services.create_section.execute(owner, course.id, "Limits")
    step = await services.create_step.execute(
        owner, course.id, section_id=section.id, title="Intro"
    )
    saved = step
    for n in range(5):
        saved = await services.save_step_draft.execute(
            owner,
            step.step_id,
            content_of("Intro", text_block(f"typing {n}")),
            saved.lock_version,
        )

    assert saved.content.blocks[0].markdown == "typing 4"
    assert saved.lock_version == step.lock_version + 5
    pending = await services.get_pending_changes.execute(owner, course.id)
    assert [s.step_id for s in pending.steps] == [step.step_id]
    history = await services.list_step_history.execute(owner, step.step_id)
    assert history == []
    row = await step_row(sessionmaker_in_tx, step.step_id)
    assert row.draft["blocks"][0]["markdown"] == "typing 4"


async def test_autosave_after_a_publish_keeps_one_pending_change(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Editing a published step many times is still a single pending change."""
    owner = course.team.owner
    seeded = await seed_published(services, owner, course.id)
    first = seeded.step_a
    saved = first
    for n in range(3):
        saved = await set_blocks(services, owner, saved, text_block(f"edit {n}"))

    pending = await services.get_pending_changes.execute(owner, course.id)
    assert [s.step_id for s in pending.steps].count(first.step_id) == 1
