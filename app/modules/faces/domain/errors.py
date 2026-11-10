"""Errors of the faces module."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)


class FaceLockedError(ConflictError):
    """A curator or administrator set the face; only staff can replace it."""

    code = "faces/locked"
    message_key = "faces-locked"


class FaceNotFoundError(NotFoundError):
    """The user has no face on file."""

    code = "faces/not-found"
    message_key = "faces-not-found"


class FaceStudentNotFoundError(NotFoundError):
    """The student does not exist."""

    code = "faces/student-not-found"
    message_key = "faces-student-not-found"


class FaceNotCuratorError(ForbiddenError):
    """The teacher does not curate the student's group."""

    code = "faces/not-curator"
    message_key = "faces-not-curator"


class FaceImageEmptyError(ValidationFailedError):
    """The upload is empty."""

    code = "faces/image-empty"
    message_key = "faces-image-empty"


class FaceImageTooLargeError(ValidationFailedError):
    """The image is over the limit. Params: max_mb."""

    code = "faces/image-too-large"
    message_key = "faces-image-too-large"


class FaceImageTypeError(ValidationFailedError):
    """The bytes are not a JPEG or a PNG."""

    code = "faces/image-type"
    message_key = "faces-image-type"


class NoFaceError(ValidationFailedError):
    """No face was found in the image."""

    code = "faces/no-face"
    message_key = "faces-no-face"


class MultipleFacesError(ValidationFailedError):
    """More than one face was found in the image."""

    code = "faces/multiple-faces"
    message_key = "faces-multiple-faces"


class DeviceNotFoundError(NotFoundError):
    """The device does not exist."""

    code = "faces/device-not-found"
    message_key = "faces-device-not-found"


class DeviceNameError(ValidationFailedError):
    """The device name is empty or too long."""

    code = "faces/device-name"
    message_key = "faces-device-name"


class DeviceUnauthorizedError(UnauthorizedError):
    """The device token is missing, unknown or revoked."""

    code = "faces/device-unauthorized"
    message_key = "faces-device-unauthorized"
