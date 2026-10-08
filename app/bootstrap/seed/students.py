"""Demo students, registered through the real registration use cases (fake EMIS)."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.bootstrap.common import make_deps
from app.bootstrap.container import Container
from app.modules.identity.application.register_errors import EmisAlreadyLinkedError
from app.modules.identity.application.register_ports import CredentialStore
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD, FakeEmisClient
from app.modules.identity.wiring_emis import build_emis

import structlog

log = structlog.get_logger(__name__)

STUDENT_PASSWORD = "StudentDemo1"
EMIS_LOGINS = ("student01", "student16")
RECOVERY_DOMAIN = "ihsu.uz"


class CapturingEmailSender:
    """EmailSender that keeps the last code instead of sending it."""

    def __init__(self) -> None:
        """Start without a code."""
        self.last_code: str | None = None

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Remember the one-time code of the message."""
        self.last_code = str(params["code"])


@dataclass(frozen=True, slots=True)
class DemoStudent:
    """A registered demo student."""

    emis_login: str
    user_id: UUID
    login: str


async def _register(
    container: Container, services: Any, sender: CapturingEmailSender, emis_login: str
) -> DemoStudent | None:
    try:
        started = await services.register_start.execute(
            emis_login=emis_login, emis_password=FAKE_PASSWORD, ip=None, locale="ru"
        )
    except EmisAlreadyLinkedError:
        return None
    token = started.registration_token
    await services.register_email_code.execute(
        registration_token=token, email=f"{emis_login}@{RECOVERY_DOMAIN}"
    )
    registered = await services.register_complete.execute(
        registration_token=token,
        password=STUDENT_PASSWORD,
        email_code=sender.last_code or "",
        confirm_import_match=True,
        login_challenge=None,
        ip=None,
        user_agent=None,
    )
    return DemoStudent(emis_login, registered.user_id, registered.login)


async def register_students(
    container: Container, credentials: CredentialStore | None = None
) -> list[DemoStudent]:
    """Register `student01` and `student16`; already registered ones are skipped.

    ``credentials`` replaces Vault (tests).
    """
    auth = container.identity.auth
    sender = CapturingEmailSender()
    services = build_emis(
        make_deps(container),
        login_acceptor=auth.login_acceptor,
        account_revoker=auth.account_revoker,
        email_sender=sender,
        otp_store=auth.otp_store,
        academic_enrollment=container.academic.schedule.enrollment,
        emis_client=FakeEmisClient(container.clock),
        credentials=credentials,
    )
    try:
        found = [await _register(container, services, sender, n) for n in EMIS_LOGINS]
    finally:
        await services.close()
    students = [student for student in found if student is not None]
    for student in students:
        log.info(
            "seed_student_registered", emis=student.emis_login, login=student.login
        )
    return students
