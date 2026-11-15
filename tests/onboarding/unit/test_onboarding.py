"""Onboarding: which steps a user sees and how they are finished."""

from app.modules.onboarding.domain.steps import Onboarding, StepKey
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from tests.faces.conftest import photo
from tests.onboarding.conftest import OnboardingHarness

import pytest


def keys(state: Onboarding) -> list[tuple[str, bool, bool]]:
    """(key, required, done) of the steps."""
    return [(s.key.value, s.required, s.done) for s in state.steps]


async def test_student_without_photo_must_take_a_selfie(oh: OnboardingHarness) -> None:
    me = oh.student()
    state = await oh.services.get_onboarding.execute(me)
    assert state.required
    assert keys(state) == [("selfie", True, False), ("certificates", False, False)]
    selfie, certs = state.steps
    assert not selfie.skippable and certs.skippable


async def test_own_selfie_satisfies_the_step(oh: OnboardingHarness) -> None:
    me = oh.student()
    await oh.faces.services.upload_my_face.execute(me.user_id, photo("a"))
    state = await oh.services.get_onboarding.execute(me)
    assert not state.required
    assert keys(state) == [("selfie", True, True), ("certificates", False, False)]


async def test_curator_photo_means_no_selfie_required(oh: OnboardingHarness) -> None:
    me = oh.student()
    group = oh.faces.directory.students[me.user_id].group_id
    oh.faces.directory.curators.add((oh.faces.curator.user_id, group))
    await oh.faces.services.staff_upload.execute(
        oh.faces.curator, me.user_id, photo("s")
    )
    state = await oh.services.get_onboarding.execute(me)
    assert not state.required
    assert [s.key for s in state.steps if not s.done] == [StepKey.CERTIFICATES]


async def test_certificates_done_is_not_shown_again(oh: OnboardingHarness) -> None:
    me = oh.student()
    await oh.faces.services.upload_my_face.execute(me.user_id, photo("a"))
    state = await oh.services.complete_certificates.execute(me)
    assert state.steps == () and not state.required
    again = await oh.services.get_onboarding.execute(me)
    assert again.steps == ()
    row = oh.store.rows[me.user_id]
    assert row.certificates_prompt_done_at is not None and row.completed_at is not None


async def test_skipping_certificates_keeps_selfie_required(
    oh: OnboardingHarness,
) -> None:
    me = oh.student()
    state = await oh.services.complete_certificates.execute(me)
    assert state.required
    assert keys(state) == [("selfie", True, False)]


async def test_done_twice_keeps_the_first_time(oh: OnboardingHarness) -> None:
    me = oh.student()
    await oh.services.complete_certificates.execute(me)
    first = oh.store.rows[me.user_id].certificates_prompt_done_at
    await oh.services.complete_certificates.execute(me)
    assert oh.store.rows[me.user_id].certificates_prompt_done_at == first


async def test_non_student_has_no_steps(oh: OnboardingHarness) -> None:
    teacher = oh.make_actor(Role.TEACHER)
    state = await oh.services.get_onboarding.execute(teacher)
    assert not state.required and state.steps == ()
    with pytest.raises(ForbiddenError):
        await oh.services.complete_certificates.execute(teacher)
    with pytest.raises(ForbiddenError):
        await oh.services.refresh_emis.execute(teacher)


async def test_refresh_imports_and_is_rate_limited(oh: OnboardingHarness) -> None:
    me = oh.student()
    for _ in range(3):
        await oh.services.refresh_emis.execute(me)
    assert oh.importer.calls == [me.user_id] * 3
    with pytest.raises(RateLimitedError):
        await oh.services.refresh_emis.execute(me)
    assert len(oh.importer.calls) == 3
