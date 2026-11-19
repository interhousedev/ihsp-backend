"""Every sealed essay column is binary in the models."""

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.infrastructure.orm.sealed import SEALED_COLUMNS, SEALED_JSON
from app.shared.db.base import Base

from sqlalchemy import LargeBinary


def test_sealed_columns_are_binary() -> None:
    """ADM-CRYPT-14: each listed column of an existing table is LargeBinary."""
    for table, columns in SEALED_COLUMNS.items():
        model = Base.metadata.tables.get(f"admission.{table}")
        if model is None:
            continue  # the table lands with another change
        for column in columns:
            assert isinstance(model.c[column].type, LargeBinary), (table, column)


def test_json_columns_are_sealed_columns() -> None:
    """ADM-CRYPT-15: a JSON column is also listed as sealed."""
    assert all(c in SEALED_COLUMNS[t] for t, c in SEALED_JSON)
