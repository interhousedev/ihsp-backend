"""NB-23: mind map options, task block and validation (§ 3.4.2)."""

from typing import Any
from uuid import uuid4

from app.modules.notebooks.domain.artifacts.kinds.mind_map import (
    HANDLER,
    MindMapOptions,
)
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.domain.prompts.common import focus_clause
from tests.notebooks.unit.domain.pack_support import (
    assert_strict,
    make_ctx,
    make_pack,
)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


def options(**raw: Any) -> MindMapOptions:
    parsed = HANDLER.parse_options(raw)
    assert isinstance(parsed, MindMapOptions)
    return parsed


def node(
    node_id: str,
    parent: str | None,
    label: str | None = None,
    refs: list[str] | None = None,
    note: str = "A note.",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent,
        "label": label or f"Label {node_id}",
        "note": note,
        "refs": ["S1:P1"] if refs is None else refs,
    }


def process(nodes: list[Any], detail: str = "overview") -> Any:
    data = {"title": "Photosynthesis", "nodes": nodes}
    return HANDLER.process(data, options(detail=detail), make_ctx())


def ids(result: Any) -> list[str]:
    return [n["id"] for n in result.content["nodes"]]


def parents(result: Any) -> dict[str, str | None]:
    return {n["id"]: n["parent_id"] for n in result.content["nodes"]}


# - - - options and prompt - - -


def test_handler_is_registered_for_the_mind_map_kind() -> None:
    """NB-23: the registry finds the module's HANDLER."""
    assert handler_for(ArtifactKind.MIND_MAP) is HANDLER
    assert HANDLER.schema_name == "nb_mind_map"
    assert HANDLER.kind is ArtifactKind.MIND_MAP


def test_defaults_are_an_overview_without_nulls() -> None:
    """NB-23: stored options echo the defaults."""
    assert HANDLER.stored_options(options()) == {"detail": "overview"}


def test_common_options_are_stored() -> None:
    """NB-23: language and source_ids are part of every kind."""
    source = uuid4()

    stored = HANDLER.stored_options(
        options(detail="detailed", language="ru", source_ids=[str(source)])
    )

    assert stored == {
        "detail": "detailed",
        "language": "ru",
        "source_ids": [str(source)],
    }


@pytest.mark.parametrize("bad", [{"detail": "huge"}, {"language": "fr"}])
def test_invalid_options_raise_invalid_options_error(bad: dict[str, Any]) -> None:
    """NB-23: pydantic errors are wrapped with details."""
    with pytest.raises(InvalidOptionsError) as caught:
        HANDLER.parse_options(bad)

    assert caught.value.params["details"]


def test_tokens_and_input_cap() -> None:
    """NB-23: 3 000 output tokens; the Studio cap for input."""
    assert HANDLER.max_tokens(options()) == 3000
    assert HANDLER.max_tokens(options(detail="detailed")) == 3000
    assert HANDLER.input_cap_tokens(150_000) == 150_000
    assert HANDLER.report_format(options()) is None


def test_strict_schema_is_flat_and_fully_required() -> None:
    """NB-23: Schemas row; nodes are a list of strict objects, no recursion."""
    schema = HANDLER.strict_schema()

    assert_strict(schema)
    item = schema["properties"]["nodes"]["items"]
    assert list(item["properties"]) == ["id", "parent_id", "label", "note", "refs"]
    assert {"type": "null"} in item["properties"]["parent_id"]["anyOf"]


def test_task_block_for_an_overview() -> None:
    """NB-23: three levels, 30 nodes, 7 children."""
    task = HANDLER.task_block(options(), None)

    assert task.startswith("Create a mind map of the main topic of the sources.")
    assert "3 levels below the root" in task
    assert "at most 7 children per node" in task
    assert "at most 30 nodes" in task
    assert "Every non-root node has refs." in task


def test_task_block_for_a_detailed_map_and_a_focus() -> None:
    """NB-23: four levels, 60 nodes, the focus appended."""
    task = HANDLER.task_block(options(detail="detailed"), "light reactions")

    assert "up to 4 levels below the root" in task
    assert "at most 60 nodes" in task
    assert task.endswith(focus_clause("light reactions"))


def test_default_title() -> None:
    """NB-23: "Mind map: <notebook>"."""
    assert HANDLER.default_title("Biology", options()) == "Mind map: Biology"


# - - - process: the happy path - - -


def test_process_returns_the_tree_with_refs_index() -> None:
    """NB-23: nodes keep ids, parents and valid refs; refs_index resolves them."""
    result = process(
        [
            node("n1", None, "Photosynthesis", ["S1:P1"]),
            node("n2", "n1", "Light reactions", ["S1:P3", "S9:P9"]),
            node("n3", "n1", "Calvin cycle", ["S1:P4", "S1:P5"]),
        ]
    )

    assert result.title == "Photosynthesis"
    assert result.content["title"] == "Photosynthesis"
    assert result.content["nodes"][1] == {
        "id": "n2",
        "parent_id": "n1",
        "label": "Light reactions",
        "note": "A note.",
        "refs": ["S1:P3"],
    }
    assert set(result.refs_index) == {"S1:P1", "S1:P3", "S1:P4", "S1:P5"}
    assert result.refs_index["S1:P3"]["source_title"] == "Source 1"


def test_process_writes_parents_before_children_in_depth_first_order() -> None:
    """NB-23: the list reads like an outline; siblings keep the model's order."""
    result = process(
        [
            node("a", None),
            node("c", "a"),
            node("b", "a"),
            node("b1", "b"),
            node("c1", "c"),
        ]
    )

    assert ids(result) == ["a", "c", "c1", "b", "b1"]


def test_process_title_falls_back_to_the_root_label() -> None:
    """NB-23: a missing title is the central topic."""
    result = HANDLER.process(
        {"nodes": [node("n1", None, "Cell biology")]}, options(), make_ctx()
    )

    assert result.title == "Cell biology"


def test_process_coerces_numeric_ids_and_fills_missing_fields() -> None:
    """NB-23: a sloppy node is repaired, not dropped."""
    result = process(
        [
            {"id": 1, "parent_id": None, "label": "Root", "refs": ["S1:P1"]},
            {"id": 2, "parent_id": 1, "label": "Child", "note": None, "refs": "S1:P2"},
        ]
    )

    assert parents(result) == {"1": None, "2": "1"}
    assert result.content["nodes"][1]["note"] == ""
    assert result.content["nodes"][1]["refs"] == []


def test_process_treats_an_empty_parent_id_as_a_root() -> None:
    """NB-23: "" is as good as null."""
    result = process([node("n1", ""), node("n2", "n1")])

    assert parents(result) == {"n1": None, "n2": "n1"}


def test_process_a_node_that_is_its_own_parent_can_be_the_root() -> None:
    """NB-23: a self-reference is not a cycle but a missing null."""
    result = process([node("n1", "n1"), node("n2", "n1")])

    assert parents(result) == {"n1": None, "n2": "n1"}


# - - - process: structure - - -


def test_process_keeps_the_first_root_and_hangs_other_roots_under_it() -> None:
    """NB-23: exactly one root."""
    result = process(
        [node("a", None), node("b", None), node("b1", "b"), node("c", None)]
    )

    assert parents(result) == {"a": None, "b": "a", "b1": "b", "c": "a"}


def test_process_without_a_root_is_invalid() -> None:
    """NB-23: zero roots cannot be repaired by guessing."""
    with pytest.raises(OutputInvalidError) as caught:
        process([node("a", "b"), node("b", "a")])

    assert "root" in caught.value.problems[0]


def test_process_keeps_the_first_of_two_nodes_with_the_same_id() -> None:
    """NB-23: unique ids; the later duplicate is dropped."""
    result = process(
        [node("a", None), node("x", "a", "First"), node("x", "a", "Second")]
    )

    assert ids(result) == ["a", "x"]
    assert result.content["nodes"][1]["label"] == "First"


def test_process_reattaches_orphans_to_the_root() -> None:
    """NB-23: a parent that does not exist means the root."""
    result = process([node("a", None), node("b", "ghost"), node("c", "b")])

    assert parents(result) == {"a": None, "b": "a", "c": "b"}


def test_process_breaks_cycles_by_hanging_them_on_the_root() -> None:
    """NB-23: no cycles; nothing is lost."""
    result = process([node("a", None), node("x", "y"), node("y", "x"), node("z", "y")])

    assert sorted(ids(result)) == ["a", "x", "y", "z"]
    assert parents(result)["x"] == "a"
    assert parents(result)["y"] == "x"
    assert parents(result)["z"] == "y"


def test_process_drops_nodes_without_an_id_or_label() -> None:
    """NB-23: nothing to show; children are re-attached to the root."""
    result = process(
        [
            node("a", None),
            node("", "a", "No id"),
            node("b", "a", "   "),
            node("c", "b", "Child of the nameless"),
        ]
    )

    assert parents(result) == {"a": None, "c": "a"}


def test_process_drops_unreadable_nodes_but_keeps_the_rest() -> None:
    """NB-23: one broken item does not fail the map."""
    result = process([node("a", None), "not a node", {"id": "b"}, node("c", "a")])

    assert ids(result) == ["a", "c"]


def test_process_overview_stops_at_three_levels_below_the_root() -> None:
    """NB-23: depth cap 3 for an overview."""
    chain = [node("n0", None)] + [node(f"n{d}", f"n{d - 1}") for d in range(1, 6)]

    result = process(chain, detail="overview")

    assert ids(result) == ["n0", "n1", "n2", "n3"]


def test_process_detailed_allows_four_levels() -> None:
    """NB-23: depth cap 4 for a detailed map."""
    chain = [node("n0", None)] + [node(f"n{d}", f"n{d - 1}") for d in range(1, 6)]

    result = process(chain, detail="detailed")

    assert ids(result) == ["n0", "n1", "n2", "n3", "n4"]


def test_process_keeps_at_most_seven_children_per_node() -> None:
    """NB-23: the eighth child and its subtree are dropped."""
    nodes = [node("r", None)] + [node(f"c{i}", "r") for i in range(1, 10)]
    nodes.append(node("deep", "c8"))

    result = process(nodes)

    assert ids(result) == ["r"] + [f"c{i}" for i in range(1, 8)]


def test_process_trims_the_node_cap_deepest_first() -> None:
    """NB-23: 30 nodes; the deepest level goes first, the last node of a level first."""
    nodes = [node("r", None)]
    for i in range(1, 8):
        nodes.append(node(f"a{i}", "r"))
        for j in range(1, 5):
            nodes.append(node(f"a{i}b{j}", f"a{i}"))
    nodes += [node("deep1", "a1b1"), node("deep2", "a1b1")]
    assert len(nodes) == 38

    result = process(nodes)

    kept = ids(result)
    assert len(kept) == 30
    assert "deep1" not in kept and "deep2" not in kept  # level three first
    assert {"a7b4", "a7b3", "a7b2", "a7b1", "a6b4", "a6b3"}.isdisjoint(kept)
    assert "a6b2" in kept and "a1b1" in kept
    assert {f"a{i}" for i in range(1, 8)} <= set(kept)  # main concepts stay


def test_process_detailed_cap_is_sixty_nodes() -> None:
    """NB-23: 60 nodes for a detailed map."""
    nodes = [node("r", None)]
    for i in range(1, 8):
        nodes.append(node(f"a{i}", "r"))
        for j in range(1, 8):
            nodes.append(node(f"a{i}b{j}", f"a{i}"))
        for j in range(1, 4):
            nodes.append(node(f"a{i}b1c{j}", f"a{i}b1"))

    result = process(nodes, detail="detailed")

    assert len(ids(result)) == 60


def test_process_never_orphans_a_node_when_trimming() -> None:
    """NB-23: every kept node's parent is kept."""
    nodes = [node("r", None)]
    for i in range(1, 8):
        nodes.append(node(f"a{i}", "r"))
        for j in range(1, 8):
            nodes.append(node(f"a{i}b{j}", f"a{i}"))

    result = process(nodes)

    kept = parents(result)
    assert all(p is None or p in kept for p in kept.values())
    assert len(kept) == 30


def test_process_cuts_labels_to_60_and_notes_to_200_characters() -> None:
    """NB-23: lengths."""
    result = process([node("a", None, "L" * 100, note="N" * 400)])

    label = result.content["nodes"][0]["label"]
    note = result.content["nodes"][0]["note"]
    assert len(label) == 60 and label.endswith("…")
    assert len(note) == 200 and note.endswith("…")


def test_process_collapses_whitespace_in_labels() -> None:
    """NB-23: labels are one line."""
    result = process([node("a", None, "  Light \n reactions ")])

    assert result.content["nodes"][0]["label"] == "Light reactions"


# - - - process: refs - - -


def test_process_keeps_nodes_with_empty_refs_in_place() -> None:
    """NB-23: structure matters more than refs."""
    result = process(
        [
            node("a", None, refs=["S1:P1"]),
            node("b", "a", refs=["S9:P9"]),
            node("c", "b", refs=[]),
        ]
    )

    assert parents(result) == {"a": None, "b": "a", "c": "b"}
    assert result.content["nodes"][1]["refs"] == []
    assert set(result.refs_index) == {"S1:P1"}


def test_process_without_any_valid_ref_is_invalid() -> None:
    """NB-23: a map nobody can trace to the sources is rejected."""
    with pytest.raises(OutputInvalidError) as caught:
        process([node("a", None, refs=["S5:P1"]), node("b", "a", refs=[])])

    assert "ref" in caught.value.problems[0]


def test_process_accepts_ref_spellings_the_pack_knows() -> None:
    """NB-23: [S1:P2] and spaces are normalised by valid_refs."""
    result = process([node("a", None, refs=["[S1:P2]", " S1 : P3 "])])

    assert result.content["nodes"][0]["refs"] == ["S1:P2", "S1:P3"]


def test_process_limits_refs_to_three_per_node() -> None:
    """NB-23: at most three labels."""
    result = process([node("a", None, refs=[f"S1:P{i}" for i in range(1, 6)])])

    assert result.content["nodes"][0]["refs"] == ["S1:P1", "S1:P2", "S1:P3"]


def test_process_refs_are_checked_against_the_pack_of_the_request() -> None:
    """NB-23: with a one-passage pack only S1:P1 is valid."""
    result = HANDLER.process(
        {
            "title": "T",
            "nodes": [node("a", None, refs=["S1:P1", "S1:P2"])],
        },
        options(),
        make_ctx(make_pack((1,))),
    )

    assert result.content["nodes"][0]["refs"] == ["S1:P1"]


# - - - process: bad documents - - -


@pytest.mark.parametrize("nodes", [None, "x", {}, []])
def test_process_requires_a_non_empty_node_list(nodes: Any) -> None:
    """NB-23: a missing or empty list triggers a repair."""
    with pytest.raises(OutputInvalidError):
        HANDLER.process({"title": "T", "nodes": nodes}, options(), make_ctx())


def test_process_with_only_unreadable_nodes_reports_the_problems() -> None:
    """NB-23: the repair prompt names what is wrong."""
    with pytest.raises(OutputInvalidError) as caught:
        process([{"id": "a"}, 5])

    assert any(p.startswith("node 1:") for p in caught.value.problems)


def test_process_looks_at_a_bounded_number_of_nodes() -> None:
    """NB-23: a runaway answer cannot make the validator slow."""
    nodes = [node("r", None)] + [node(f"n{i}", "r") for i in range(2000)]

    result = process(nodes)

    assert len(ids(result)) <= 30


@settings(max_examples=200, deadline=None)
@given(
    spec=st.lists(
        st.tuples(st.integers(0, 15), st.none() | st.integers(0, 17)),
        min_size=1,
        max_size=80,
    ),
    detail=st.sampled_from(["overview", "detailed"]),
)
def test_process_gives_a_valid_tree_for_any_parent_graph(
    spec: list[tuple[int, int | None]], detail: str
) -> None:
    """NB-23: whatever the parent links, the result is one rooted, capped tree."""
    nodes = [node(f"n{i}", None if p is None else f"n{p}") for i, p in spec]

    first_parent: dict[int, int | None] = {}
    for i, p in spec:
        first_parent.setdefault(i, p)  # a repeated id is dropped
    has_root = any(p is None or p == i for i, p in first_parent.items())
    try:
        result = process(nodes, detail=detail)
    except OutputInvalidError:
        assert not has_root  # only "no root" may fail
        return
    assert has_root

    stored = result.content["nodes"]
    by_id = {n["id"]: n for n in stored}
    assert len(by_id) == len(stored)
    roots = [n for n in stored if n["parent_id"] is None]
    assert len(roots) == 1 and stored[0] is roots[0]
    assert len(stored) <= {"overview": 30, "detailed": 60}[detail]
    max_depth = {"overview": 3, "detailed": 4}[detail]
    children: dict[str, int] = {}
    for n in stored:
        depth, current = 0, n
        while current["parent_id"] is not None:
            current = by_id[current["parent_id"]]
            depth += 1
            assert depth <= max_depth
        if n["parent_id"] is not None:
            children[n["parent_id"]] = children.get(n["parent_id"], 0) + 1
    assert all(count <= 7 for count in children.values())
