"""Find or create the teacher an EMIS timetable names (ACA-1, ID-5, ID-10)."""

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.domain.audit_event import USER_CREATED, USER_UPDATED
from app.modules.identity.domain.login_name import base_login, next_free
from app.modules.identity.domain.teacher_match import matching_teachers
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id
from app.shared.text import title_case

import structlog

log = structlog.get_logger(__name__)


async def ensure_teacher(
    uow_factory: UowFactory,
    *,
    emis_teacher_id: int | None,
    first_name: str,
    last_name: str,
    middle_name: str | None,
) -> UserRef:
    """Return the teacher: by EMIS id, else by name, else a new pending account.

    A new account has the teacher role, status ``pending_activation`` and no email:
    Administration adds the email later (PATCH /v1/admin/teachers/{id}), which sends
    the activation link. Idempotent, so two timetables naming the same teacher (or
    the same timetable imported twice) never create two accounts.
    """
    first, last = title_case(first_name), title_case(last_name)
    middle = title_case(middle_name or "") or None
    async with uow_factory() as uow:
        user = await _find(uow, emis_teacher_id, first, last, middle)
        if user is None:
            user = await _create(uow, emis_teacher_id, first, last, middle)
        elif emis_teacher_id is not None and user.emis_teacher_id is None:
            user.emis_teacher_id = emis_teacher_id
            await uow.users.save(user)
            uow.audit(make_audit(USER_UPDATED, user_id=user.id, via="emis"))
        await uow.commit()
    return user.to_ref()


async def _find(
    uow: IdentityUnitOfWorkPort,
    emis_teacher_id: int | None,
    first: str,
    last: str,
    middle: str | None,
) -> User | None:
    if emis_teacher_id is not None:
        linked = await uow.users.get_by_emis_teacher_id(emis_teacher_id)
        if linked is not None:
            return linked
    candidates = matching_teachers(
        await uow.users.list_with_roles([Role.TEACHER]),
        emis_teacher_id=emis_teacher_id,
        first_name=first,
        last_name=last,
        middle_name=middle,
    )
    if len(candidates) > 1:
        log.warning("ambiguous_emis_teacher", last_name=last, first_name=first)
        return None
    return candidates[0] if candidates else None


async def _create(
    uow: IdentityUnitOfWorkPort,
    emis_teacher_id: int | None,
    first: str,
    last: str,
    middle: str | None,
) -> User:
    base = base_login(last, first)
    user = User(
        id=new_id(),
        first_name=first,
        last_name=last,
        middle_name=middle,
        login=next_free(base, await uow.users.logins_with_prefix(base)),
        roles={Role.TEACHER},
        status=UserStatus.PENDING_ACTIVATION,
        emis_teacher_id=emis_teacher_id,
    )
    await uow.users.add(user)
    uow.audit(make_audit(USER_CREATED, user_id=user.id, roles=["teacher"], via="emis"))
    return user
