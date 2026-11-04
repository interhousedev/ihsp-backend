"""AI-OPENUI: the prompt teaches every field, nested field and enum value."""

from app.shared.openui.catalog import Prop, PropType, Subset, load_catalog
from app.shared.openui.finalize import catalog_lines
from app.shared.openui.prompt import openui_prompt

import pytest


def _names_in(kind: PropType) -> list[str]:
    """Field names and enum values nested under one prop type."""
    found: list[str] = []
    if kind.type == "enum":
        found.extend(kind.values)
    if kind.of is not None:
        found.extend(_names_in(kind.of))
    for field in kind.fields:
        found.append(field.name)
        found.extend(_names_in(field.kind))
    return found


def _required_names(prop: Prop) -> list[str]:
    return [prop.name, *_names_in(prop.kind)]


@pytest.mark.parametrize("subset", ["chat", "studio"])
def test_every_component_line_names_its_props_fields_and_enum_values(
    subset: Subset,
) -> None:
    """AI-OPENUI: nothing the model must fill in is hidden behind a bare `list`."""
    lines = catalog_lines(subset).splitlines()
    components = load_catalog().in_subset(subset)
    assert len(lines) == len(components)
    for component, line in zip(components, lines, strict=True):
        assert line.startswith(f"- {component.name}(")
        for prop in component.props:
            for name in _required_names(prop):
                assert name in line, f"{component.name}: {name} missing from {line}"


@pytest.mark.parametrize("subset", ["chat", "studio"])
def test_openui_prompt_carries_the_catalog_lines(subset: Subset) -> None:
    """AI-OPENUI: the prompt includes the per-component lines verbatim."""
    prompt = openui_prompt(subset)
    assert catalog_lines(subset) in prompt


def test_enum_values_and_nested_items_are_spelled_out() -> None:
    """AI-OPENUI: the model sees the allowed tones and the shape of a list item."""
    lines = catalog_lines("chat")
    assert "tone?: enum(body|muted|heading)" in lines
    assert "items: list<{label: string, value: text, hint?: string}>[max 8]" in lines
    assert "url: url" in lines
