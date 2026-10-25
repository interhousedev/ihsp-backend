"""List rooms with their links and PINs (ADM-19, UF-ADM-16)."""

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.application.schedule.room_views import build_room_data
from app.shared.clock import Clock


class ListRooms:
    """Return rooms with the page URL and lessons this week."""

    def __init__(self, uow_factory: UowFactory, clock: Clock, rooms_url: str) -> None:
        """Store the dependencies; rooms_url is URLS__ROOMS."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.rooms_url = rooms_url

    async def execute(self, status: str | None = None) -> list[RoomData]:
        """Return rooms ordered by name, optionally of one status."""
        async with self.uow_factory() as uow:
            rooms = await uow.rooms.list_all(status)
            return await build_room_data(
                uow, rooms, today=today(self.clock), base_url=self.rooms_url
            )
