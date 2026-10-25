"""One way to declare an enumeration column (VARCHAR plus CHECK constraint)."""

from enum import StrEnum

from sqlalchemy import Enum


def str_enum(values: type[StrEnum], name: str) -> Enum:
    """A non-native `Enum` column type holding every value of `values`.

    All values of all phases are listed, so later phases need no constraint change.
    """
    return Enum(
        *(member.value for member in values),
        name=name,
        native_enum=False,
        create_constraint=True,
    )
