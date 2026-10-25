"""Certificate types: create, edit, delete and the protection of built-ins."""

from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CertificateTypeBuiltinError,
    CertificateTypeCodeTakenError,
    CertificateTypeInUseError,
    CertificateTypeNotFoundError,
)
from tests.certificates.conftest import CertificatesHarness, number_field

import pytest

NAME = {"uz": "Test", "ru": "Тест", "en": "Test"}


async def test_admin_creates_a_custom_type_after_the_last_position(
    h: CertificatesHarness,
) -> None:
    """Custom types are not built in and get the next position."""
    await h.add_type("ielts", position=4)

    kind = await h.services.create_type.execute(
        {
            "code": "toefl",
            "name": NAME,
            "custom_fields": [
                {
                    "key": "level",
                    "kind": "single",
                    "label": NAME,
                    "options": ["80", "100"],
                }
            ],
        }
    )

    assert (kind.builtin, kind.position) == (False, 5)
    assert [(f.key, f.options) for f in kind.custom_fields] == [
        ("level", ("80", "100"))
    ]


async def test_a_code_cannot_be_used_twice(h: CertificatesHarness) -> None:
    """Creating a type with a taken code is a conflict."""
    await h.add_type("sat")

    with pytest.raises(CertificateTypeCodeTakenError):
        await h.services.create_type.execute({"code": "sat", "name": NAME})


@pytest.mark.parametrize(
    "fields",
    [
        {"code": "Bad Code", "name": NAME},
        {"code": "ok", "name": {"uz": "x", "ru": "", "en": "x"}},
        {
            "code": "ok",
            "name": NAME,
            "custom_fields": [
                {"key": "level", "kind": "single", "label": NAME, "options": ["A", "A"]}
            ],
        },
        {
            "code": "ok",
            "name": NAME,
            "custom_fields": [
                {"key": "score", "kind": "number", "label": NAME, "min": 10, "max": 1}
            ],
        },
    ],
)
async def test_an_unusable_type_is_refused(
    h: CertificatesHarness, fields: dict[str, object]
) -> None:
    """Bad code, empty name, repeated choices and an inverted range fail."""
    with pytest.raises(CertificateInvalidError):
        await h.services.create_type.execute(fields)


async def test_admin_edits_a_type(h: CertificatesHarness) -> None:
    """Only the sent fields change."""
    kind = await h.add_type("sat", custom_fields=[number_field("score")])

    changed = await h.services.update_type.execute(
        kind.id,
        {
            "custom_fields": [
                {
                    "key": "score",
                    "kind": "number",
                    "label": NAME,
                    "min": 400,
                    "max": 1600,
                }
            ]
        },
    )

    assert [(f.min_value, f.max_value) for f in changed.custom_fields] == [(400, 1600)]


async def test_a_builtin_type_keeps_its_code_but_can_be_renamed(
    h: CertificatesHarness,
) -> None:
    """The code of a built-in type is fixed; its other fields are editable."""
    kind = await h.add_type("cefr", builtin=True)

    with pytest.raises(CertificateTypeBuiltinError):
        await h.services.update_type.execute(kind.id, {"code": "other"})
    renamed = await h.services.update_type.execute(
        kind.id, {"code": "cefr", "name": NAME}
    )

    assert renamed.name == NAME


async def test_a_type_cannot_take_another_types_code(h: CertificatesHarness) -> None:
    """Renaming the code onto an existing one is a conflict."""
    await h.add_type("sat")
    other = await h.add_type("ap")

    with pytest.raises(CertificateTypeCodeTakenError):
        await h.services.update_type.execute(other.id, {"code": "sat"})


async def test_a_builtin_type_cannot_be_deleted(h: CertificatesHarness) -> None:
    """Deleting a built-in type is a conflict."""
    kind = await h.add_type("national", builtin=True)

    with pytest.raises(CertificateTypeBuiltinError):
        await h.services.delete_type.execute(kind.id)


async def test_a_type_with_entries_cannot_be_deleted(h: CertificatesHarness) -> None:
    """A type in use stays."""
    kind = await h.add_type("sat")
    await h.add_entry(h.ann, kind)

    with pytest.raises(CertificateTypeInUseError):
        await h.services.delete_type.execute(kind.id)


async def test_an_unused_custom_type_is_deleted(h: CertificatesHarness) -> None:
    """The type disappears from the list."""
    kind = await h.add_type("sat")

    await h.services.delete_type.execute(kind.id)

    assert await h.services.list_types.execute() == []
    with pytest.raises(CertificateTypeNotFoundError):
        await h.services.delete_type.execute(kind.id)
