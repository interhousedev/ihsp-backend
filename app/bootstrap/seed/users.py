"""Demo accounts: the administrator and five teachers (no activation link needed)."""

from dataclasses import dataclass
from uuid import UUID

from app.bootstrap.container import Container
from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

ADMIN_LOGIN = "admin.ihsp"
ADMIN_PASSWORD = "AdminDemo1"
TEACHER_PASSWORD = "TeacherDemo1"
LIBRARIAN_LOGIN = "tursunov.sardor"
LIBRARIAN_PASSWORD = "LibrarianDemo1"
MAIL_DOMAIN = "ihsu.uz"


@dataclass(frozen=True, slots=True)
class TeacherSpec:
    """One demo teacher."""

    key: str
    last_name: str
    first_name: str

    @property
    def login(self) -> str:
        """`<surname>.<name>` in lower case."""
        return f"{self.last_name}.{self.first_name}".lower()


TEACHERS: tuple[TeacherSpec, ...] = (
    TeacherSpec("math", "Usmonov", "Bobur"),
    TeacherSpec("languages", "Karimova", "Nodira"),
    TeacherSpec("it", "Rahimov", "Sherzod"),
    TeacherSpec("uzbek", "Saidova", "Malika"),
    TeacherSpec("humanities", "Aliyev", "Javlon"),
)


async def _ensure(
    container: Container,
    *,
    login: str,
    first_name: str,
    last_name: str,
    password: str,
    roles: set[Role],
) -> UUID:
    auth = container.identity.auth
    async with auth.uow_factory() as uow:
        existing = await uow.users.get_by_login(login)
        if existing is not None:
            return existing.id
        admin = Role.ADMIN in roles
        user = User(
            id=new_id(),
            first_name=first_name,
            last_name=last_name,
            login=login,
            password_hash=await auth.hasher.hash(password),
            roles=roles,
            recovery_email=f"{login}@{MAIL_DOMAIN}",
            recovery_email_verified_at=container.clock.now(),
            otp_enabled=admin,
            otp_via_email=admin,
            status=UserStatus.ACTIVE,
            preferences={"locale": "ru"},
        )
        await uow.users.add(user)
        await uow.commit()
    log.info("seed_user_created", login=login)
    return user.id


async def ensure_admin(container: Container) -> UUID:
    """The administrator `admin.ihsp`; sign-in asks for a code mailed to Mailpit."""
    return await _ensure(
        container,
        login=ADMIN_LOGIN,
        first_name="Admin",
        last_name="IHSP",
        password=ADMIN_PASSWORD,
        roles={Role.ADMIN, Role.LMS_ADMIN},
    )


async def ensure_teachers(container: Container) -> dict[str, UUID]:
    """The five teachers, by key."""
    return {
        spec.key: await _ensure(
            container,
            login=spec.login,
            first_name=spec.first_name,
            last_name=spec.last_name,
            password=TEACHER_PASSWORD,
            roles={Role.TEACHER},
        )
        for spec in TEACHERS
    }


async def ensure_librarian(container: Container) -> UUID:
    """The demo librarian `tursunov.sardor`, apart from the students who upload."""
    return await _ensure(
        container,
        login=LIBRARIAN_LOGIN,
        first_name="Sardor",
        last_name="Tursunov",
        password=LIBRARIAN_PASSWORD,
        roles={Role.LIBRARIAN},
    )
