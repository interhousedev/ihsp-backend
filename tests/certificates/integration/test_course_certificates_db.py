"""Course certificates on PostgreSQL: idempotent issue, upgrade, revoke, verify."""

from app.modules.certificates.application.course_certificates import (
    CourseCertificates,
)
from app.modules.certificates.domain.errors import (
    CertificateUploadRejectedError,
    CourseCertificateForbiddenError,
    CourseCertificateNotFoundError,
)
from app.shared.ids import new_id
from tests.certificates.course_world import Facts, enable, make_world

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def world(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> tuple[CourseCertificates, Facts]:
    """The service on the test transaction."""
    return make_world(sessionmaker_in_tx)


async def test_issue_is_idempotent_upgrades_and_verifies(
    world: tuple[CourseCertificates, Facts],
) -> None:
    """Same row on repeat; tier goes up in place; revoked shows as revoked."""
    service, facts = world
    await enable(service, facts)
    learner, lazy = new_id(), new_id()
    facts.results = {learner: (2, 70), lazy: (1, 50)}

    first = await service.issue_if_eligible(facts.course_id, learner)
    again = await service.issue_if_eligible(facts.course_id, learner)
    assert first is not None and again is not None
    assert again.id == first.id and again.code == first.code
    assert first.tier_key == "normal" and first.holder_name == "Oʻgʻiloy Qahhorova"
    assert await service.issue_if_eligible(facts.course_id, lazy) is None

    facts.results[learner] = (2, 95)
    upgraded = await service.issue_if_eligible(facts.course_id, learner)
    assert upgraded is not None and upgraded.code == first.code
    assert upgraded.tier_key == "honors"
    facts.results[learner] = (2, 70)
    kept = await service.issue_if_eligible(facts.course_id, learner)
    assert kept is not None and kept.tier_key == "honors"

    assert await service.issue_eligible(facts.manager, facts.course_id) == 1
    status = await service.mine(lazy, facts.course_id)
    assert not status.eligible and status.certificate is None

    verified = await service.verify(first.code.lower())
    assert verified.revoked_at is None and verified.course_title == "Physics 10"
    name, pdf = await service.pdf(learner, first.id)
    assert pdf.startswith(b"%PDF") and first.code in name
    with pytest.raises(CourseCertificateNotFoundError):
        await service.pdf(lazy, first.id)

    with pytest.raises(CourseCertificateForbiddenError):
        await service.revoke(learner, facts.course_id, first.id, "mine")
    await service.revoke(facts.manager, facts.course_id, first.id, "Plagiarism")
    assert (await service.verify(first.code)).revoked_at is not None
    again_after = await service.issue_if_eligible(facts.course_id, learner)
    assert again_after is not None and again_after.revoked_at is not None
    with pytest.raises(CourseCertificateNotFoundError):
        await service.verify("NOPE00000000")


async def test_background_upload_is_validated(
    world: tuple[CourseCertificates, Facts],
) -> None:
    """A fake PDF is refused; staff only."""
    service, facts = world
    template = await service.create_template(facts.manager, facts.course_id, "T")
    with pytest.raises(CertificateUploadRejectedError):
        await service.upload_background(
            facts.manager, facts.course_id, template.id, b"%PDF-1.4 not really"
        )
    with pytest.raises(CourseCertificateForbiddenError):
        await service.upload_background(new_id(), facts.course_id, template.id, b"x")
