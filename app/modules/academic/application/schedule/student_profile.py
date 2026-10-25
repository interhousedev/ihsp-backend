"""The logged-in student's profile (WEB-16)."""

from app.modules.academic.application.schedule.common import UowFactory, person_map
from app.modules.academic.application.schedule.results import StudentProfileData
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    StudentNotFoundError,
)
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.identity import IdentityDirectory


class GetStudentProfile:
    """Return the student's group, subgroup, curator and mailbox."""

    def __init__(
        self,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        mail_domain: str,
    ) -> None:
        """Store the dependencies; mail_domain is SMTP_OUT__MAIL_DOMAIN."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.mail_domain = mail_domain

    async def execute(self, actor: Actor) -> StudentProfileData:
        """Return the profile of the actor, who must be a student."""
        user = await self.identity.get_user(actor.user_id)
        if user is None:
            raise NotFoundError()
        async with self.uow_factory() as uow:
            student = await uow.students.get(actor.user_id)
            if student is None:
                raise StudentNotFoundError()
            group = await uow.groups.get(student.group_id)
        if group is None:
            raise GroupNotFoundError()
        people = await person_map(
            self.identity, [group.curator_id, group.head_student_id]
        )
        return StudentProfileData(
            user_id=user.id,
            login=user.login,
            first_name=user.first_name,
            last_name=user.last_name,
            mailbox=f"{user.login}@{self.mail_domain}" if user.login else None,
            group_id=group.id,
            group_name=group.name,
            subgroup=student.subgroup,
            curator=people.get(group.curator_id) if group.curator_id else None,
            head_student=(
                people.get(group.head_student_id) if group.head_student_id else None
            ),
            current_semester=group.current_semester,
            emis_status=user.emis_status,
            synced_at=student.synced_at,
        )
