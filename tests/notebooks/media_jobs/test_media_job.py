"""ONE media job: voice-over and video are stages of the same `MediaJob`.

Replaces the separate narration and HyperFrames render jobs. A teacher picks the
output (`video_with_voice` or `audio_only`), one script and one voice; the job voices
the script, renders the video when asked, and stores the result in the subject
notebook as text with segment timecodes (no transcription of the finished media).

The implementation must provide:
- `app.modules.media.domain.media_job`: `MediaKind` {VIDEO_WITH_VOICE, AUDIO_ONLY};
  `MediaStatus` {QUEUED, VOICING, RENDERING, DONE, FAILED}; `MediaJob` dataclass
  (id, owner_id, kind, script: tuple[Segment, ...], options: NarrationOptions,
  subject_id, group_id|None, status, attempts, max_attempts=3, audio_file_id,
  captions_file_id, file_id, storage_key, segments (aligned), duration_ms, error,
  created_at) built by `MediaJob.queue(owner_id, kind, script, options, now, *,
  subject_id, group_id=None)`; `script_hash` (stable over text+voice+kind).
  Transitions: `start()` QUEUED->VOICING (attempts+=1); `voiced(audio_file_id,
  captions_file_id, segments, duration_ms)` VOICING->RENDERING for video, ->DONE for
  audio (then `file_id` is the audio file); `complete(file_id, storage_key)`
  RENDERING->DONE; `fail(reason)` (VOICING|RENDERING)->QUEUED while attempts <
  max_attempts else FAILED; `cancel()` QUEUED|VOICING|RENDERING->FAILED "cancelled".
  Illegal moves raise `InvalidMediaTransitionError` (ConflictError).
  `MediaJob.storage_key_for(owner_id, script_hash, kind)` ->
  `media/jobs/<owner>/<hash>.mp4` (video) or `.mp3` (audio).
  `MediaJob.deliverables` -> ("mp4",) for video, ("mp3",) for audio. Never an
  HyperFrames project or any other technical export.
- `app.modules.media.application.media_job`: `EnqueueMediaJob(store, kicker, clock,
  limits)`.execute(actor, kind, script, options, *, subject_id, group_id=None) ->
  MediaJob (validates the script; kicks `media.run_job` on queue `media_render`; the
  same script_hash by the same owner returns the existing DONE job; over
  `media_jobs_per_week` -> `MediaLimitError`; estimated length > 180 s ->
  ValidationFailedError); `RunMediaJob(store, synthesizer, renderer, files,
  notebook_sink)`.execute(job_id): voice, then render for video, store, then
  `notebook_sink.store(actor, material)`; `GetMediaJob(store).execute(actor, job_id)`
  owner-only (others, even teachers: NotFoundError; admin may read).

Review fixes (round 3):
- Access. Media is standalone teacher material, scoped by SUBJECT/GROUP (not by a
  course): `EnqueueMediaJob(store, kicker, clock, limits, scope)` refuses a
  student/parent and a destination `scope.can_teach` denies (ForbiddenError, nothing
  queued). Attaching the result to an LMS step is a separate apply action that needs
  course `edit`. Before any paid step the worker revalidates through `OwnerAccess.
  actor_for(owner_id, subject_id, group_id) -> Actor | None`; None (revoked) cancels the
  job (FAILED) with nothing synthesized.
- DONE means delivered: `MediaJob.delivered` is False until the notebook accepted the
  material (`mark_delivered()`, DONE only). A sink failure leaves the job DONE,
  undelivered; `RunMediaJob.execute` on it retries ONLY the delivery (never
  re-synthesizes), a sweeper job `media.deliver_pending` redelivers undelivered DONE
  jobs. Enqueue returns an existing job only when it is DONE AND delivered, for the
  same owner, script_hash AND destination; an undelivered one is re-kicked.
- Destination is NOT part of the content: a repeat of the same script for another
  subject/group makes a new job that reuses the already rendered files (found through
  `store.find_done(owner_id, script_hash)`), skips voice and render, and delivers to
  its own notebook.
- Resumable: the job row is the state. A redelivered `execute` on a job left in
  VOICING/RENDERING by a crashed worker calls `recover()` (-> QUEUED, or FAILED "worker
  lost" when attempts are used) and continues; on DONE it does nothing but a pending
  delivery. Concurrent duplicate workers are excluded by optimistic `version` on
  `store.save` (the loser exits; a DB test belongs to the implementation). Cancelling
  during synthesis: the worker re-checks the status before it stores any file.
- The renderer gets the aligned `segments` (scenes) and the voice track; the real
  renderer is additionally covered by a decodable-media integration test (ffprobe of
  the mp4/mp3 with the actual local ffmpeg/TTS fixtures).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.modules.media.application.media_job import (
    EnqueueMediaJob,
    GetMediaJob,
    ListMediaJobs,
    MediaLimitError,
    RetryMediaJob,
    RunMediaJob,
)
from app.modules.media.domain.media_job import (
    InvalidMediaTransitionError,
    MediaJob,
    MediaKind,
    MediaStatus,
)
from app.modules.media.domain.narration import (
    NarrationInvalidError,
    NarrationOptions,
    Segment,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.shared.ids import new_id
from tests.factories import make_actor as build_actor
from tests.notebooks.material_sink.fakes import FakeScope
from tests.notebooks.media_jobs.fakes import (
    FakeAccess,
    FakeFiles,
    FakeMediaJobStore,
    FakeNotebookSink,
    FakeRenderer,
    FakeSpeechSynthesizer,
)

import pytest

NOW = datetime(2026, 11, 27, tzinfo=UTC)
OPTIONS = NarrationOptions("lecture", "short", "en", "voice-1", 1.0)
SCRIPT = (
    Segment("s1", "teacher", "Hello class"),
    Segment("s2", "teacher", "Light bends"),
)
SUBJECT = new_id()


def queued(kind: MediaKind = MediaKind.VIDEO_WITH_VOICE, **kw: Any) -> MediaJob:
    return MediaJob.queue(
        kw.get("owner", new_id()),
        kind,
        SCRIPT,
        OPTIONS,
        NOW,
        subject_id=SUBJECT,
        group_id=kw.get("group_id"),
    )


def voice(job: MediaJob) -> None:
    job.start()
    job.voiced(new_id(), new_id(), SCRIPT, 3000)


def test_video_goes_through_voice_then_render() -> None:
    job = queued()
    assert job.status is MediaStatus.QUEUED and job.attempts == 0

    job.start()
    assert job.status is MediaStatus.VOICING and job.attempts == 1
    job.voiced(new_id(), new_id(), SCRIPT, 3000)
    assert job.status is MediaStatus.RENDERING

    file_id = new_id()
    job.complete(file_id, "media/jobs/x.mp4")
    assert (
        job.status is MediaStatus.DONE and job.file_id == file_id and job.error is None
    )


def test_audio_only_finishes_after_the_voice_stage() -> None:
    job = queued(MediaKind.AUDIO_ONLY)
    job.start()
    audio = new_id()
    job.voiced(audio, new_id(), SCRIPT, 3000)

    assert job.status is MediaStatus.DONE and job.file_id == audio
    assert job.duration_ms == 3000


def test_done_is_delivered_only_after_the_notebook_accepted_it() -> None:
    job = queued(MediaKind.AUDIO_ONLY)
    voice(job)
    assert job.status is MediaStatus.DONE and job.delivered is False

    job.mark_delivered()

    assert job.delivered is True
    with pytest.raises(InvalidMediaTransitionError):
        queued().mark_delivered()  # only a DONE job can be delivered


def test_a_crashed_stage_is_recovered_until_attempts_are_used() -> None:
    job = queued()
    job.start()  # worker died here
    job.recover()
    assert job.status is MediaStatus.QUEUED and job.attempts == 1

    for _ in range(job.max_attempts - 1):
        job.start()
        job.recover()
    assert job.status is MediaStatus.FAILED and job.error == "worker lost"
    with pytest.raises(InvalidMediaTransitionError):
        queued().recover()  # QUEUED has nothing to recover


def test_users_only_get_mp4_or_mp3() -> None:
    """No HyperFrames project, zip or other technical export is ever offered."""
    assert queued().deliverables == ("mp4",)
    assert queued(MediaKind.AUDIO_ONLY).deliverables == ("mp3",)


def test_failure_requeues_until_attempts_are_used() -> None:
    job = queued()
    for attempt in range(1, job.max_attempts):
        job.start()
        job.fail("crash")
        assert job.status is MediaStatus.QUEUED and job.attempts == attempt
    job.start()
    job.fail("crash again")

    assert job.status is MediaStatus.FAILED and job.error == "crash again"


def test_a_render_failure_requeues_from_the_render_stage() -> None:
    job = queued()
    voice(job)
    job.fail("chromium crashed")

    assert job.status is MediaStatus.QUEUED


@pytest.mark.parametrize(
    "action",
    [
        lambda j: j.complete(new_id(), "k"),  # QUEUED -> DONE
        lambda j: j.fail("x"),  # QUEUED -> fail
        lambda j: j.voiced(new_id(), new_id(), SCRIPT, 1),  # QUEUED -> voiced
    ],
)
def test_illegal_transitions_from_queued(action: Any) -> None:
    with pytest.raises(InvalidMediaTransitionError) as err:
        action(queued())
    assert isinstance(err.value, ConflictError)


def test_audio_job_cannot_be_rendered() -> None:
    job = queued(MediaKind.AUDIO_ONLY)
    job.start()
    job.voiced(new_id(), new_id(), SCRIPT, 1)
    with pytest.raises(InvalidMediaTransitionError):
        job.complete(new_id(), "k")


def test_terminal_states_are_final() -> None:
    done = queued(MediaKind.AUDIO_ONLY)
    voice(done)
    failed = queued()
    failed.cancel()

    for job in (done, failed):
        for action in (job.start, lambda j=job: j.fail("x"), lambda j=job: j.cancel()):
            with pytest.raises(InvalidMediaTransitionError):
                action()
    assert failed.status is MediaStatus.FAILED and failed.error == "cancelled"


def test_storage_key_is_deterministic_owner_scoped_and_typed() -> None:
    owner = new_id()
    video = MediaJob.storage_key_for(owner, "abc", MediaKind.VIDEO_WITH_VOICE)
    audio = MediaJob.storage_key_for(owner, "abc", MediaKind.AUDIO_ONLY)

    assert video == f"media/jobs/{owner}/abc.mp4"
    assert audio == f"media/jobs/{owner}/abc.mp3"
    assert video != MediaJob.storage_key_for(
        new_id(), "abc", MediaKind.VIDEO_WITH_VOICE
    )


def test_script_hash_depends_on_text_voice_and_kind() -> None:
    a, b = queued(), queued()
    other_kind = queued(MediaKind.AUDIO_ONLY)

    assert a.script_hash == b.script_hash != other_kind.script_hash


@pytest.mark.parametrize(
    "script,options",
    [
        (
            (
                Segment("s1", "teacher", "Hello class"),
                Segment("s2", "teacher", "Light bends!"),
            ),
            OPTIONS,
        ),
        (SCRIPT, NarrationOptions("lecture", "short", "en", "voice-2", 1.0)),
        (SCRIPT, NarrationOptions("lecture", "short", "en", "voice-1", 1.25)),
        (SCRIPT, NarrationOptions("lecture", "short", "ru", "voice-1", 1.0)),
    ],
)
def test_script_hash_changes_with_text_voice_speed_or_language(
    script: Any, options: Any
) -> None:
    base = queued().script_hash
    other = MediaJob.queue(
        new_id(), MediaKind.VIDEO_WITH_VOICE, script, options, NOW, subject_id=SUBJECT
    )

    assert other.script_hash != base


def test_the_destination_is_not_part_of_the_content_hash() -> None:
    assert queued(group_id=new_id()).script_hash == queued().script_hash


class Kicker:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, tuple]] = []

    async def kick(self, task: str, *args: Any, queue: str = "default") -> None:
        self.sent.append((task, queue, args))


class Limits:
    media_jobs_per_week = 2

    def __init__(self, used: int = 0) -> None:
        self.used = used

    async def used_this_week(self, owner_id: Any) -> int:
        return self.used


@pytest.fixture
def rig() -> SimpleNamespace:
    store, kicker, limits = FakeMediaJobStore(), Kicker(), Limits()
    clock, scope, access = SimpleNamespace(now=lambda: NOW), FakeScope(), FakeAccess()
    synth, files, renderer, sink = (
        FakeSpeechSynthesizer(),
        FakeFiles(),
        FakeRenderer(),
        FakeNotebookSink(),
    )
    return SimpleNamespace(
        store=store,
        kicker=kicker,
        limits=limits,
        synth=synth,
        files=files,
        renderer=renderer,
        sink=sink,
        scope=scope,
        access=access,
        enqueue=EnqueueMediaJob(store, kicker, clock, limits, scope),
        run=RunMediaJob(store, synth, renderer, files, sink, access),
        list=ListMediaJobs(store),
        retry=RetryMediaJob(store, kicker),
    )


def teacher_of(rig: SimpleNamespace, *groups: Any) -> Any:
    """A teacher who teaches SUBJECT now (and the given groups)."""
    teacher = build_actor(Role.TEACHER)
    rig.scope.allow(teacher, SUBJECT, None)
    for group in groups:
        rig.scope.allow(teacher, SUBJECT, group)
    return teacher


async def _enqueue(
    rig: SimpleNamespace,
    actor: Actor,
    kind: Any = MediaKind.VIDEO_WITH_VOICE,
    script: Any = SCRIPT,
    **kw: Any,
) -> Any:
    return await rig.enqueue.execute(
        actor, kind, script, OPTIONS, subject_id=SUBJECT, **kw
    )


async def test_enqueue_stores_a_queued_job_and_kicks_the_media_queue(
    rig: SimpleNamespace,
) -> None:
    teacher = teacher_of(rig)

    job = await _enqueue(rig, teacher)

    assert job.status is MediaStatus.QUEUED and job.owner_id == teacher.user_id
    assert rig.store.jobs[job.id] is job
    assert rig.kicker.sent == [("media.run_job", "media_render", (str(job.id),))]


async def test_invalid_script_is_refused_before_anything_is_queued(
    rig: SimpleNamespace,
) -> None:
    with pytest.raises(NarrationInvalidError):
        await _enqueue(rig, teacher_of(rig), script=())
    assert rig.kicker.sent == [] and rig.store.jobs == {}


async def test_same_script_returns_the_finished_job(rig: SimpleNamespace) -> None:
    teacher = teacher_of(rig)
    first = await _enqueue(rig, teacher)
    voice(first)
    first.complete(new_id(), "k")
    first.mark_delivered()

    again = await _enqueue(rig, teacher)

    assert again.id == first.id and len(rig.kicker.sent) == 1


async def test_weekly_limit_and_length_cap(rig: SimpleNamespace) -> None:
    teacher = teacher_of(rig)
    rig.limits.used = 2
    with pytest.raises(MediaLimitError):
        await _enqueue(rig, teacher)

    rig.limits.used = 0
    long = (Segment("s1", "teacher", "word " * 4000),)
    with pytest.raises(ValidationFailedError):
        await _enqueue(rig, teacher, script=long)
    assert rig.kicker.sent == []


async def test_worker_makes_one_mp4_from_the_voice_track(rig: SimpleNamespace) -> None:
    teacher = teacher_of(rig)
    job = await _enqueue(rig, teacher)

    await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert saved.status is MediaStatus.DONE
    name, content, mime = rig.files.blobs[saved.file_id]
    assert mime == "video/mp4" and name.endswith(".mp4")
    assert rig.renderer.last_audio is not None, "the video carries the voice-over"
    assert [c[2] for c in rig.synth.calls] == ["voice-1", "voice-1"]
    assert saved.segments[1].start_ms == saved.segments[0].end_ms
    assert (
        rig.renderer.last_segments == saved.segments
    ), "scenes come from the aligned script"
    assert saved.delivered is True
    assert saved.storage_key == MediaJob.storage_key_for(
        teacher.user_id, saved.script_hash, MediaKind.VIDEO_WITH_VOICE
    )


async def test_audio_only_never_calls_the_renderer(rig: SimpleNamespace) -> None:
    job = await _enqueue(rig, teacher_of(rig), MediaKind.AUDIO_ONLY)

    await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert saved.status is MediaStatus.DONE and rig.renderer.calls == 0
    assert rig.files.blobs[saved.file_id][2] == "audio/mpeg"


async def test_captions_are_stored_with_the_voice_track(rig: SimpleNamespace) -> None:
    job = await _enqueue(rig, teacher_of(rig), MediaKind.AUDIO_ONLY)

    await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert rig.files.blobs[saved.captions_file_id][2] == "text/vtt"


async def test_finished_job_goes_to_the_subject_notebook_with_timecodes(
    rig: SimpleNamespace,
) -> None:
    group = new_id()
    teacher = teacher_of(rig, group)
    job = await _enqueue(rig, teacher, group_id=group)

    await rig.run.execute(job.id)

    (material,) = rig.sink.stored
    assert material.kind == "media"
    assert (material.subject_id, material.group_id) == (SUBJECT, group)
    assert [(s.start_ms, s.end_ms) for s in material.segments] == [
        (s.start_ms, s.end_ms) for s in rig.store.jobs[job.id].segments
    ]
    assert material.media_file_id == rig.store.jobs[job.id].file_id


async def test_failed_job_stores_nothing_in_the_notebook(rig: SimpleNamespace) -> None:
    rig.synth.fail_on = "Light"
    job = await _enqueue(rig, teacher_of(rig))

    await rig.run.execute(job.id)

    assert rig.sink.stored == [] and rig.files.blobs == {}


async def test_worker_failure_requeues_then_succeeds(rig: SimpleNamespace) -> None:
    rig.renderer.failures = 1
    job = await _enqueue(rig, teacher_of(rig))

    await rig.run.execute(job.id)
    assert rig.store.jobs[job.id].status is MediaStatus.QUEUED

    await rig.run.execute(job.id)
    assert rig.store.jobs[job.id].status is MediaStatus.DONE
    assert len(rig.sink.stored) == 1


async def test_worker_gives_up_after_max_attempts(rig: SimpleNamespace) -> None:
    rig.renderer.failures = 99
    job = await _enqueue(rig, teacher_of(rig))

    for _ in range(job.max_attempts):
        await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert saved.status is MediaStatus.FAILED and saved.error
    assert rig.sink.stored == []


async def test_cancelled_job_is_not_processed(rig: SimpleNamespace) -> None:
    job = await _enqueue(rig, teacher_of(rig))
    job.cancel()

    await rig.run.execute(job.id)

    assert rig.renderer.calls == 0 and rig.synth.calls == []


async def test_only_the_owner_reads_the_job(rig: SimpleNamespace) -> None:
    owner = teacher_of(rig)
    job = await _enqueue(rig, owner)
    get = GetMediaJob(rig.store)

    assert (await get.execute(owner, job.id)).id == job.id
    assert (await get.execute(build_actor(Role.ADMIN), job.id)).id == job.id
    with pytest.raises(NotFoundError):
        await get.execute(teacher_of(rig), job.id)


async def test_students_and_parents_cannot_enqueue(rig: SimpleNamespace) -> None:
    for role in (Role.STUDENT, Role.COUNSELOR):
        actor = build_actor(role)
        rig.scope.allow(actor, SUBJECT, None)
        with pytest.raises(ForbiddenError):
            await _enqueue(rig, actor)

    assert rig.store.jobs == {} and rig.kicker.sent == []


async def test_a_destination_the_teacher_does_not_teach_is_refused(
    rig: SimpleNamespace,
) -> None:
    teacher = teacher_of(rig)  # teaches SUBJECT as a whole only

    with pytest.raises(ForbiddenError):
        await rig.enqueue.execute(
            teacher, MediaKind.AUDIO_ONLY, SCRIPT, OPTIONS, subject_id=new_id()
        )
    with pytest.raises(ForbiddenError):
        await _enqueue(rig, teacher, group_id=new_id())

    assert rig.store.jobs == {} and rig.kicker.sent == []


async def test_access_revoked_before_the_worker_runs_fails_without_spending(
    rig: SimpleNamespace,
) -> None:
    job = await _enqueue(rig, teacher_of(rig))
    rig.access.revoked = True

    await rig.run.execute(job.id)

    assert rig.store.jobs[job.id].status is MediaStatus.FAILED
    assert rig.synth.calls == [] and rig.renderer.calls == 0 and rig.sink.stored == []


async def test_same_script_for_another_group_is_delivered_there_without_new_synthesis(
    rig: SimpleNamespace,
) -> None:
    first_group, second_group = new_id(), new_id()
    teacher = teacher_of(rig, first_group, second_group)
    first = await _enqueue(rig, teacher, group_id=first_group)
    await rig.run.execute(first.id)
    synth_calls, renders = len(rig.synth.calls), rig.renderer.calls

    second = await _enqueue(rig, teacher, group_id=second_group)
    await rig.run.execute(second.id)

    assert second.id != first.id
    assert rig.store.jobs[second.id].status is MediaStatus.DONE
    assert rig.store.jobs[second.id].file_id == rig.store.jobs[first.id].file_id
    assert (len(rig.synth.calls), rig.renderer.calls) == (synth_calls, renders)
    assert [m.group_id for m in rig.sink.stored] == [first_group, second_group]


async def test_sink_failure_keeps_done_undelivered_and_a_rerun_only_delivers(
    rig: SimpleNamespace,
) -> None:
    rig.sink.failures = 1
    job = await _enqueue(rig, teacher_of(rig))

    await rig.run.execute(job.id)
    saved = rig.store.jobs[job.id]
    assert saved.status is MediaStatus.DONE and saved.delivered is False
    assert rig.sink.stored == []
    synth_calls, renders = len(rig.synth.calls), rig.renderer.calls

    await rig.run.execute(job.id)

    assert rig.store.jobs[job.id].delivered is True and len(rig.sink.stored) == 1
    assert (len(rig.synth.calls), rig.renderer.calls) == (synth_calls, renders)


async def test_duplicate_delivery_of_a_delivered_job_does_nothing(
    rig: SimpleNamespace,
) -> None:
    job = await _enqueue(rig, teacher_of(rig))
    await rig.run.execute(job.id)
    synth_calls, renders = len(rig.synth.calls), rig.renderer.calls

    await rig.run.execute(job.id)

    assert len(rig.sink.stored) == 1
    assert (len(rig.synth.calls), rig.renderer.calls) == (synth_calls, renders)


async def test_a_job_left_mid_stage_by_a_crashed_worker_is_resumed_on_redelivery(
    rig: SimpleNamespace,
) -> None:
    job = await _enqueue(rig, teacher_of(rig))
    job.start()  # the first worker died after claiming the job

    await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert (
        saved.status is MediaStatus.DONE
        and saved.delivered is True
        and saved.attempts == 2
    )


async def test_cancel_during_synthesis_stores_nothing(rig: SimpleNamespace) -> None:
    job = await _enqueue(rig, teacher_of(rig))

    def cancel_once() -> None:
        if rig.store.jobs[job.id].status is MediaStatus.VOICING:
            rig.store.jobs[job.id].cancel()

    rig.synth.on_call = cancel_once

    await rig.run.execute(job.id)

    saved = rig.store.jobs[job.id]
    assert saved.status is MediaStatus.FAILED and saved.error == "cancelled"
    assert rig.files.blobs == {} and rig.sink.stored == [] and rig.renderer.calls == 0


async def test_list_returns_only_my_jobs_newest_first_paginated(
    rig: SimpleNamespace,
) -> None:
    mine, other = teacher_of(rig), teacher_of(rig)
    jobs = [
        await _enqueue(rig, mine, script=(Segment("s", "t", f"text {i}"),))
        for i in range(3)
    ]
    await _enqueue(rig, other)
    for n, job in enumerate(jobs):
        job.created_at = NOW.replace(minute=n)

    page, total = await rig.list.execute(mine, limit=2, offset=0)
    rest, _ = await rig.list.execute(mine, limit=2, offset=2)

    assert total == 3
    assert [j.id for j in page] == [jobs[2].id, jobs[1].id]
    assert [j.id for j in rest] == [jobs[0].id]


async def test_retry_requeues_a_failed_job_and_kicks_the_worker(
    rig: SimpleNamespace,
) -> None:
    teacher = teacher_of(rig)
    job = await _enqueue(rig, teacher)
    job.cancel()
    rig.kicker.sent.clear()

    again = await rig.retry.execute(teacher, job.id)

    assert again.status is MediaStatus.QUEUED and again.error is None
    assert again.attempts == 0
    assert rig.kicker.sent == [("media.run_job", "media_render", (str(job.id),))]


async def test_retry_refuses_a_job_that_did_not_fail(rig: SimpleNamespace) -> None:
    teacher = teacher_of(rig)
    job = await _enqueue(rig, teacher)

    with pytest.raises(ConflictError):
        await rig.retry.execute(teacher, job.id)


async def test_retry_of_a_foreign_job_is_not_found(rig: SimpleNamespace) -> None:
    job = await _enqueue(rig, teacher_of(rig))
    job.cancel()

    with pytest.raises(NotFoundError):
        await rig.retry.execute(teacher_of(rig), job.id)
