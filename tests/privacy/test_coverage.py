"""Every table with a user column is described for the export and the erasure."""

from app.bootstrap.adapters.personal_data import all_specs
from app.shared.db.base import Base  # noqa: F401  (imports every model)

import pytest

USER_COLUMNS = {"user_id", "owner_id"}


def test_every_user_table_has_a_spec() -> None:
    """A new table keyed by a user must be added to ``SPECS`` of its module."""
    assert len(Base.metadata.tables) > 50, "models are not imported"
    described = {spec.name for spec in all_specs()}
    missing = sorted(
        f"{t.schema}.{t.name}"
        for t in Base.metadata.tables.values()
        if USER_COLUMNS & set(t.c.keys()) and f"{t.schema}.{t.name}" not in described
    )
    if missing:
        pytest.fail(f"no personal-data spec for: {missing}")
