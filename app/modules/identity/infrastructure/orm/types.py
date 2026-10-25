"""Column types used by the identity ORM models."""

from typing import Any

from sqlalchemy import Dialect, TypeDecorator
from sqlalchemy.dialects.postgresql import INET


class InetStr(TypeDecorator[str]):
    """PostgreSQL inet that always reads back as str (asyncpg returns objects)."""

    impl = INET
    cache_ok = True

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        """Convert ipaddress objects to their string form."""
        return None if value is None else str(value)
