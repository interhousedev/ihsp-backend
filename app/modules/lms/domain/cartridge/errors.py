"""Errors of cartridge import and export."""

from app.shared.base_error import NotFoundError, ValidationFailedError


class CartridgeInvalidError(ValidationFailedError):
    """The upload is not a readable Common Cartridge.

    ``params["reason"]`` says why: ``not-zip``, ``too-large``, ``too-many-files``,
    ``unsafe-path``, ``bomb``, ``no-manifest``, ``bad-manifest``, ``bad-xml``,
    ``empty``.
    """

    code = "lms/cartridge-invalid"
    message_key = "lms-cartridge-invalid"


class CartridgeImportNotFoundError(NotFoundError):
    """No such import job, or it belongs to someone else, or it expired."""

    code = "lms/cartridge-import-not-found"
    message_key = "lms-cartridge-import-not-found"
