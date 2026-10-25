"""LIB-12: every message of the UniLibrary area exists in uz, ru and en."""

from app.modules.library.domain.errors import (
    ExternalDisabledError,
    ExternalUnavailableError,
)
from app.modules.library.domain.external_errors import (
    ExternalSyncUnavailableError,
    FeedNotFoundError,
    FieldMapInvalidError,
)
from app.shared.i18n.core import I18nCore

import pytest

KEYS = [
    ExternalDisabledError.message_key,
    ExternalUnavailableError.message_key,
    ExternalSyncUnavailableError.message_key,
    FeedNotFoundError.message_key,
    FieldMapInvalidError.message_key,
    "library-external-access-any",
    "library-external-access-open",
    "library-external-access-partial",
    "library-external-access-closed",
]


@pytest.mark.parametrize("locale", ["uz", "ru", "en"])
@pytest.mark.parametrize("key", KEYS)
def test_message_is_translated(i18n: I18nCore, locale: str, key: str) -> None:
    """LIB-12: no key falls back to itself."""
    assert i18n.t(locale, key) != key
