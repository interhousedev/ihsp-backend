"""NB-AUTO: a text is read, chunked, summarized and described once for all students."""

from app.modules.notebooks.application.build_source_guide import (
    WAIT_STEPS,
    BuildSourceGuide,
)
from app.modules.notebooks.application.light_json import LightJson
from app.modules.notebooks.domain.entities import Notebook, SourceGuide
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.source_input import LessonResourceInput
from app.modules.notebooks.infrastructure.redis_guide_lock import RedisGuideLock
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.links import make_resource
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import (
    GUIDE,
    SUMMARY,
    HookedLlm,
    add_one,
    add_ready,
    passages_of,
    stored,
)

TEXT = "Photosynthesis turns light into chemical energy in the chloroplasts."
EXPECTED = SourceGuide(
    summary=GUIDE["summary"],
    key_topics=GUIDE["key_topics"],
    questions=GUIDE["questions"],
)


async def _lesson_input(world: World, student: Actor) -> LessonResourceInput:
    """A teacher's file (its own upload) on a lesson the student attends."""
    lesson = world.schedule.attend(student.user_id, make_lesson())
    ref = world.files.add_text(make_file(lesson.id, name="Waves.pdf"), TEXT)
    resource = world.links.add(make_resource(lesson.id, title="Waves", file_id=ref.id))
    return LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id)


async def test_a_file_read_for_one_student_is_not_read_again_for_the_next(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-AUTO: thirty students with one lesson file cost one reading."""
    lesson = world.schedule.attend(student.user_id, make_lesson())
    world.schedule.attend(other_student.user_id, lesson)
    ref = world.files.add_text(make_file(lesson.id, name="Waves.pdf"), TEXT)
    resource = world.links.add(make_resource(lesson.id, title="Waves", file_id=ref.id))
    item = LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id)

    mine = await add_ready(sources, uow_factory, student, notebook, item)
    theirs = await add_ready(sources, uow_factory, other_student, their_notebook, item)

    assert world.files.read_calls == [ref.id]
    assert mine.status is theirs.status is SourceStatus.READY
    assert mine.document_id == theirs.document_id is not None
    assert (mine.passage_count, mine.content_hash) == (
        theirs.passage_count,
        theirs.content_hash,
    )
    assert [p.id for p in await passages_of(uow_factory, mine.id)] == [
        p.id for p in await passages_of(uow_factory, theirs.id)
    ]


async def test_two_files_with_the_same_text_share_one_document(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-AUTO: two uploads of the same slides give the same document by text."""
    first = await _lesson_input(world, student)
    second = await _lesson_input(world, other_student)

    mine = await add_ready(sources, uow_factory, student, notebook, first)
    theirs = await add_ready(
        sources, uow_factory, other_student, their_notebook, second
    )

    assert len(world.files.read_calls) == 2  # two files, two readings ...
    assert mine.document_id == theirs.document_id is not None  # ... one stored text


async def test_a_deleted_file_is_not_served_from_the_shared_text(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """FILE-6: once a file is deleted its text does not come back through sharing."""
    lesson = world.schedule.attend(student.user_id, make_lesson())
    world.schedule.attend(other_student.user_id, lesson)
    ref = world.files.add_text(make_file(lesson.id, name="Waves.pdf"), TEXT)
    resource = world.links.add(make_resource(lesson.id, title="Waves", file_id=ref.id))
    item = LessonResourceInput(lesson_id=lesson.id, link_id=resource.link_id)
    await add_ready(sources, uow_factory, student, notebook, item)
    waiting = await add_one(sources, other_student, their_notebook, item)
    world.files.delete(ref.id)

    await sources.process_source.execute(waiting.id)

    failed = await stored(uow_factory, waiting.id)
    assert failed.status is SourceStatus.FAILED
    assert failed.failure is SourceFailure.DELETED
    assert failed.document_id is None


async def test_the_guide_is_written_once_for_everyone_who_holds_the_text(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    scripted_llm: HookedLlm,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-AUTO: the second student's guide costs no model call and no budget."""
    mine = await make_source(uow_factory, notebook, title="Waves", texts=(TEXT,))
    theirs = await make_source(
        uow_factory, their_notebook, title="Waves", texts=(TEXT,)
    )
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(mine.id)
    await sources.build_source_guide.execute(theirs.id)

    assert len(scripted_llm.json_requests) == 1
    for source in (mine, theirs):
        saved = await stored(uow_factory, source.id)
        assert saved.guide == EXPECTED and saved.guide_status is GuideStatus.READY


async def test_a_guide_waits_for_the_worker_that_is_already_writing_it(
    core: NotebooksCore,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-AUTO: 30 students opening one file at once do not make 30 calls."""
    source = await make_source(uow_factory, notebook, title="Waves", texts=(TEXT,))
    assert source.document_id is not None
    lock = RedisGuideLock(core.deps.redis)
    assert await lock.try_claim(source.document_id, "en") is not None
    document_id = source.document_id
    naps: list[float] = []

    async def other_worker_finishes(seconds: float) -> None:
        naps.append(seconds)
        async with uow_factory() as uow:
            await uow.documents.save_guide(document_id, "en", EXPECTED)
            await uow.commit()

    job = BuildSourceGuide(
        uow_factory=uow_factory,
        clock=core.deps.clock,
        light=LightJson(llm=core.llm, budget=core.budget),
        locale=core.locale,
        lock=lock,
        sleep=other_worker_finishes,
    )

    await job.execute(source.id)

    assert len(naps) == 1 and scripted_llm.json_requests == []
    assert (await stored(uow_factory, source.id)).guide == EXPECTED


async def test_a_guide_is_written_by_us_when_the_other_worker_never_finishes(
    core: NotebooksCore,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-AUTO: a crashed worker delays the guide by 45 seconds, no more."""
    source = await make_source(uow_factory, notebook, title="Waves", texts=(TEXT,))
    assert source.document_id is not None
    lock = RedisGuideLock(core.deps.redis)
    await lock.try_claim(source.document_id, "en")
    naps: list[float] = []

    async def nap(seconds: float) -> None:
        naps.append(seconds)

    scripted_llm.queue_json(GUIDE)
    job = BuildSourceGuide(
        uow_factory=uow_factory,
        clock=core.deps.clock,
        light=LightJson(llm=core.llm, budget=core.budget),
        locale=core.locale,
        lock=lock,
        sleep=nap,
    )

    await job.execute(source.id)

    assert len(naps) == WAIT_STEPS and len(scripted_llm.json_requests) == 1
    assert (await stored(uow_factory, source.id)).guide == EXPECTED


async def test_the_summary_is_built_once_for_the_same_set_of_texts(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    other_student: Actor,
    clock: FixedClock,
) -> None:
    """NB-AUTO: two notebooks with the same files get one summary and one model call."""
    books = []
    for owner in (student, other_student):
        book = await make_notebook(
            uow_factory,
            owner.user_id,
            summary_status=SummaryStatus.STALE,
            summary_due_at=clock.now(),
        )
        await make_source(
            uow_factory,
            book,
            title="Waves",
            texts=(TEXT,),
            guide=EXPECTED,
            guide_status=GuideStatus.READY,
        )
        books.append(book)
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 2

    assert len(scripted_llm.json_requests) == 1
    async with uow_factory() as uow:
        saved = [await uow.notebooks.get(book.id) for book in books]
    first, second = saved
    assert first is not None and second is not None
    assert first.summary == second.summary and first.summary is not None
    assert first.summary_hash == second.summary_hash
    assert first.summary_status is second.summary_status is SummaryStatus.READY
