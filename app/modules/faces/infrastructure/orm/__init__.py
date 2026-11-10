"""ORM models of the faces schema."""

from app.modules.faces.infrastructure.orm.tables import (
    DeviceCallRow,
    DeviceRow,
    FaceProfileRow,
    PassageRow,
)

__all__ = ["DeviceCallRow", "DeviceRow", "FaceProfileRow", "PassageRow"]
