"""Term standings of the caller's group: the shared step of the "My group" views."""

from dataclasses import dataclass
from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.errors import NoGroupError
from app.modules.academic.domain.marks.group_standing import (
    METRICS,
    SCOPES,
    GroupStanding,
    Metric,
    Scope,
    StudentStanding,
    current_term,
    group_rankings,
    group_standings,
    in_scope,
)
from app.modules.academic.domain.marks.read_models import GroupRoles
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


@dataclass(frozen=True, slots=True)
class Standings:
    """The caller's group with the term aggregates of every student."""

    group: GroupRoles
    students: list[StudentStanding]
    groups: list[GroupStanding]

    def mine(self) -> GroupStanding | None:
        """The caller's group aggregates."""
        return next((g for g in self.groups if g.group_id == self.group.id), None)

    def rankings(self, scope: Scope, metric: Metric) -> list[dict[str, Any]]:
        """Ranked groups of the scope with place and value; never their members.

        Groups without a value (no marks or no attendance this term) are left out.
        """
        mine = self.mine()
        course = mine.course if mine else self.group.course
        return [
            {
                "place": place,
                "group_id": g.group_id,
                "group_name": g.group_name,
                "course": g.course,
                "value": _round(g.value(metric)),
                "members_count": g.members_count,
                "is_mine": g.group_id == self.group.id,
            }
            for place, g in group_rankings(in_scope(self.groups, scope, course), metric)
            if place is not None
        ]

    def ranks(self) -> dict[str, Any]:
        """The caller's group place per scope and metric (None when unranked)."""
        result: dict[str, Any] = {}
        for scope in SCOPES:
            result[scope] = {}
            for metric in METRICS:
                rows = self.rankings(scope, metric)
                place = next((r["place"] for r in rows if r["is_mine"]), None)
                total = len(rows)
                result[scope][metric] = (
                    None if place is None else {"place": place, "total": total}
                )
        return result


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


async def load_standings(
    uow_factory: MarksUowFactory, clock: Clock, actor: Actor
) -> Standings:
    """Read the caller's group and the current-term aggregates in two queries."""
    async with uow_factory() as uow:
        ctx = await uow.reader.student_context(actor.user_id)
        group = None if ctx is None else await uow.reader.group_roles(ctx.group_id)
        if group is None:
            raise NoGroupError()
        term = current_term(await uow.reader.terms(), local_today(clock))
        students = [] if term is None else await uow.reader.term_standings(*term)
    return Standings(group=group, students=students, groups=group_standings(students))
