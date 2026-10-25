"""A stored UniLibrary record that UniLibrary no longer has (`gone`, doc 3.3).

The record stays on shelves and lists as "no longer available" and leaves search, so
the item keeps its status; `external.gone_at` carries the fact.
"""

from datetime import datetime

from app.modules.library.domain.entities import Item


def mark_gone(item: Item, now: datetime) -> bool:
    """Note that UniLibrary lost the record; False when it was already noted."""
    if item.external is None or item.external.gone_at is not None:
        return False
    item.external.gone_at = now
    item.updated_at = now
    return True


def clear_gone(item: Item, now: datetime) -> bool:
    """The record is back; False when it was not marked gone."""
    if item.external is None or item.external.gone_at is None:
        return False
    item.external.gone_at = None
    item.updated_at = now
    return True
