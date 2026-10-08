"""Who may manage a group: its curator or Administration."""

from app.modules.academic.domain.schedule.errors import NotGroupCuratorError
from app.modules.academic.domain.schedule.group import Group
from app.shared.actor import Actor, Role


def ensure_curator_or_admin(actor: Actor, group: Group) -> None:
    """Raise unless the actor is an admin or the group's curator."""
    if actor.has(Role.ADMIN):
        return
    if actor.has(Role.TEACHER) and group.curator_id == actor.user_id:
        return
    raise NotGroupCuratorError()
