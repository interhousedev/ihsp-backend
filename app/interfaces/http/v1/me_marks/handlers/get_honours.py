"""GET /v1/me/honours."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_marks.schemas import (
    HonourAward,
    HonourBlocking,
    HonourRule,
    HonoursResponse,
)
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_honours(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> HonoursResponse:
    """Return the student's eligibility for the red diploma and the medals."""
    settings = await container.admin.platform_settings.current()
    awards, serial = await container.academic.marks.get_honours.execute(
        actor, settings.honours
    )
    return HonoursResponse(
        awards=[
            HonourAward(
                kind=award.kind,
                eligible=award.eligible,
                rules=[
                    HonourRule(
                        rule=rule.rule,
                        passed=rule.passed,
                        blocking=[
                            HonourBlocking(
                                subject_id=b.subject_id,
                                subject_name=b.subject_name,
                                semester=b.semester,
                                type=b.type,
                                value=b.value,
                            )
                            for b in rule.blocking
                        ],
                    )
                    for rule in award.rules
                ],
            )
            for award in awards
        ],
        school_certificate_serial=serial,
    )
