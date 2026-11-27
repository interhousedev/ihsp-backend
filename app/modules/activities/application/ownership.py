"""Ownership transfer between active members."""

from uuid import UUID

from app.modules.activities.application.common import (
    load_club,
    note,
    require,
)
from app.modules.activities.domain.access import Permission, PermissionDeniedError
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.membership import MemberRole, Membership
from app.modules.activities.domain.ownership import (
    OwnershipTransfer,
    TransferStatus,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor, Role
from app.shared.notifications import NotificationType


class OwnershipService:
    """Offer, accept, decline, cancel, expire and force transfers."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def _get(self, transfer_id: UUID) -> OwnershipTransfer:
        t = await self._p.transfers.get(transfer_id)
        if t is None:
            raise ActivitiesNotFoundError()
        return t

    async def offer(
        self, actor: Actor, club_id: UUID, to_user_id: UUID
    ) -> OwnershipTransfer:
        """The owner offers the club to an active member."""
        p = self._p
        await require(p, actor, club_id, Permission.TRANSFER)
        club = await load_club(p, club_id)
        target = await p.members.get(club_id, to_user_id)
        t = OwnershipTransfer.offer(
            club_id,
            club.owner_id or actor.user_id,
            to_user_id,
            p.clock.now(),
            target is not None and target.is_active,
        )
        await p.transfers.add(t)
        await p.notifier.send(
            [
                note(
                    to_user_id,
                    NotificationType.CLUB_TRANSFER_OFFER,
                    {
                        "club_id": str(club_id),
                        "transfer_id": str(t.id),
                        "club_name": club.name,
                    },
                    f"activities:transfer:{t.id}",
                )
            ]
        )
        return t

    async def accept(self, actor: Actor, transfer_id: UUID) -> OwnershipTransfer:
        """Only the recipient accepts; roles swap."""
        p = self._p
        t = await self._get(transfer_id)
        if actor.user_id != t.to_user:
            raise PermissionDeniedError()
        members = await self._pair(t.club_id, t.from_user, t.to_user)
        t.accept(p.clock.now(), members)
        for m in members.values():
            await p.members.save(m)
        await p.transfers.save(t)
        await p.audit.record(actor.user_id, "activities.club.transfer", t.club_id)
        await self._tell_offerer(t, "accepted")
        return t

    async def incoming(self, actor: Actor) -> list[OwnershipTransfer]:
        """Open, unexpired offers addressed to the actor."""
        now = self._p.clock.now()
        return [
            t
            for t in await self._p.transfers.list_offered()
            if t.to_user == actor.user_id and t.expires_at > now
        ]

    async def _tell_offerer(self, t: OwnershipTransfer, result: str) -> None:
        """Tell the offerer how the recipient answered."""
        club = await self._p.clubs.get(t.club_id)
        payload: dict[str, object] = {
            "club_id": str(t.club_id),
            "transfer_id": str(t.id),
            "club_name": club.name if club else "",
            "result": result,
        }
        await self._p.notifier.send(
            [
                note(
                    t.from_user,
                    NotificationType.CLUB_TRANSFER_OFFER,
                    payload,
                    f"activities:transfer:{t.id}:{result}",
                )
            ]
        )

    async def _pair(self, club_id: UUID, a: UUID, b: UUID) -> dict[UUID, Membership]:
        out: dict[UUID, Membership] = {}
        for uid in (a, b):
            m = await self._p.members.get(club_id, uid)
            if m is not None:
                out[uid] = m
        return out

    async def decline(self, actor: Actor, transfer_id: UUID) -> OwnershipTransfer:
        """The recipient says no."""
        t = await self._get(transfer_id)
        if actor.user_id != t.to_user:
            raise PermissionDeniedError()
        t.decline()
        await self._p.transfers.save(t)
        await self._tell_offerer(t, "declined")
        return t

    async def cancel(self, actor: Actor, transfer_id: UUID) -> OwnershipTransfer:
        """The offerer withdraws."""
        t = await self._get(transfer_id)
        if actor.user_id != t.from_user:
            raise PermissionDeniedError()
        t.cancel()
        await self._p.transfers.save(t)
        return t

    async def force_transfer(
        self, actor: Actor, club_id: UUID, to_user_id: UUID
    ) -> None:
        """SU hands the club over without an offer."""
        p = self._p
        if Role.SU not in actor.roles:
            raise PermissionDeniedError()
        club = await load_club(p, club_id)
        target = await p.members.get(club_id, to_user_id)
        if target is None or not target.is_active:
            raise ActivitiesNotFoundError()
        old = await p.members.get(club_id, club.owner_id) if club.owner_id else None
        if old is not None and old.user_id != to_user_id:
            old.role = MemberRole.CO_OWNER
            await p.members.save(old)
        target.role = MemberRole.OWNER
        await p.members.save(target)
        await p.audit.record(actor.user_id, "activities.club.force_transfer", club_id)

    async def expire_due(self) -> int:
        """Close offers older than the TTL."""
        p = self._p
        now = p.clock.now()
        n = 0
        for t in await p.transfers.list_offered():
            if now >= t.expires_at and t.status == TransferStatus.OFFERED:
                t.expire(now)
                await p.transfers.save(t)
                n += 1
        return n

    async def graduation_alerts(self) -> int:
        """Tell owners in their final year to hand the club over."""
        p = self._p
        graduating = await p.users.graduating()
        year = p.clock.now().year
        sent = 0
        for club in await p.clubs.list_all():
            club = await load_club(p, club.id)
            if club.owner_id in graduating:
                await p.notifier.send(
                    [
                        note(
                            club.owner_id,
                            NotificationType.CLUB_OWNER_GRADUATING,
                            {"club_id": str(club.id)},
                            f"activities:graduating:{club.id}:{year}",
                        )
                    ]
                )
                sent += 1
        return sent
