"""A device asks who is at the door."""

from datetime import datetime

from app.modules.faces.application.views import IdentifiedStudent, IdentifyResult
from app.modules.faces.domain.device_token import hash_token, looks_like_token
from app.modules.faces.domain.errors import (
    DeviceUnauthorizedError,
    MultipleFacesError,
)
from app.modules.faces.domain.image import SNIFF_BYTES, check_image
from app.modules.faces.domain.models import (
    CallStatus,
    Device,
    DeviceCall,
    Direction,
    Passage,
    best_match,
)
from app.modules.faces.ports.directory import StudentDirectory, StudentInfo
from app.modules.faces.ports.engine import FaceEngine, ImageSniffer
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.excuses import ExcuseStatus, ExcuseStatusReader
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.rate_limit import RateLimiter

NOT_RECOGNISED = IdentifyResult(student=None, excused=False, excuse_until=None)


class AuthenticateDevice:
    """Resolves a bearer token to a live device and records its use."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, token: str) -> Device:
        """Return the device or raise `DeviceUnauthorizedError`."""
        if not looks_like_token(token):
            raise DeviceUnauthorizedError()
        async with self._uow_factory() as uow:
            device = await uow.devices.by_hash(hash_token(token))
            if device is None or device.revoked_at is not None:
                raise DeviceUnauthorizedError()
            await uow.devices.touch(device.id, self._clock.now())
            await uow.commit()
        return device


class IdentifyFace:
    """Match the photo against the stored faces and log the call."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        auth: AuthenticateDevice,
        engine: FaceEngine,
        sniffer: ImageSniffer,
        directory: StudentDirectory,
        excuses: ExcuseStatusReader,
        rate_limiter: RateLimiter,
        clock: Clock,
        threshold: float,
        per_minute: int,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._auth = auth
        self._engine = engine
        self._sniffer = sniffer
        self._directory = directory
        self._excuses = excuses
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._threshold = threshold
        self._per_minute = per_minute

    async def execute(
        self, token: str, direction: Direction, image: bytes
    ) -> IdentifyResult:
        """Return the recognised student, or an empty result when nobody matches."""
        device = await self._auth.execute(token)
        await self._rate_limiter.hit(
            f"faces:device:{device.id}", limit=self._per_minute, window_seconds=60
        )
        check_image(image, await self._sniffer.sniff(image[:SNIFF_BYTES]))
        now = self._clock.now()
        try:
            probe = await self._engine.embed(image)
        except MultipleFacesError:
            await self._log(device, now, CallStatus.MULTIPLE_FACES)
            return NOT_RECOGNISED
        if probe is None:
            await self._log(device, now, CallStatus.NO_FACE)
            return NOT_RECOGNISED
        async with self._uow_factory() as uow:
            candidates = await uow.profiles.embeddings()
        user_id = best_match(probe, candidates, self._threshold)
        student = await self._directory.student(user_id) if user_id else None
        if user_id is None or student is None:
            await self._log(device, now, CallStatus.NO_MATCH)
            return NOT_RECOGNISED
        status = await self._excuses.status(user_id, now)
        async with self._uow_factory() as uow:
            await uow.activity.add_call(
                DeviceCall(
                    new_id(), device.id, now, CallStatus.MATCHED, user_id,
                    status.excused_now,
                )
            )  # fmt: skip
            passage = Passage(
                new_id(), device.id, user_id, now, direction, status.excused_now
            )
            await uow.activity.add_passage(passage)
            alert = _exit_alert(direction, passage, student, status)
            if alert is not None:
                uow.notify(alert)
            await uow.commit()
        return IdentifyResult(
            student=IdentifiedStudent(user_id, student.full_name, student.group_name),
            excused=status.excused_now,
            excuse_until=status.until.isoformat() if status.until else None,
        )

    async def _log(self, device: Device, at: datetime, status: CallStatus) -> None:
        """Write a call that matched nobody."""
        async with self._uow_factory() as uow:
            await uow.activity.add_call(
                DeviceCall(new_id(), device.id, at, status, None, None)
            )
            await uow.commit()


def _exit_alert(
    direction: Direction, passage: Passage, student: StudentInfo, status: ExcuseStatus
) -> NotificationDraft | None:
    """The curator's alert when a student walks out in lesson time without excuse."""
    curator_id = status.curator_id
    if (
        direction is not Direction.OUT
        or not status.in_lesson_time
        or status.excused_now
        or curator_id is None
    ):
        return None
    return NotificationDraft(
        user_id=curator_id,
        type=NotificationType.GATE_UNEXCUSED_EXIT,
        payload={
            "student_id": str(student.user_id),
            "student_name": student.full_name,
            "group_id": str(student.group_id),
            "group_name": student.group_name,
            "at": passage.at.isoformat(),
        },
        dedupe_key=f"gate-exit:{passage.id}",
    )
