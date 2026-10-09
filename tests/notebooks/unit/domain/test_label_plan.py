"""G12: how an auto run merges the model's labels into a notebook."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from app.modules.notebooks.domain.label_output import ParsedLabel, ParsedLabels
from app.modules.notebooks.domain.label_plan import LabelPlan, plan_labels
from app.modules.notebooks.domain.labels import LabelLink, LabelOrigin, SourceLabel
from app.shared.ids import new_id

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
NOTEBOOK = new_id()
S1, S2, S3 = new_id(), new_id(), new_id()
SOURCES = {"s1": S1, "s2": S2, "s3": S3}


def stored(
    name: str, origin: LabelOrigin = LabelOrigin.AUTO, position: int = 1
) -> SourceLabel:
    """An existing label."""
    return SourceLabel(new_id(), NOTEBOOK, name, "🏷️", position, origin, NOW)


def parsed(
    names: list[str], assignments: dict[str, list[int]] | None = None
) -> ParsedLabels:
    """A cleaned answer: label `n` is named `names[n]`, keys are l0, l1, ..."""
    labels = [ParsedLabel(f"l{n}", name, "🧬") for n, name in enumerate(names)]
    given = assignments or {"s1": [0]}
    return ParsedLabels(labels, {s: [f"l{n}" for n in ns] for s, ns in given.items()})


def run(
    labels: list[SourceLabel],
    links: list[LabelLink],
    answer: ParsedLabels,
    sources: dict[str, UUID] | None = None,
) -> LabelPlan:
    """Plan a run with sequential ids."""
    return plan_labels(
        notebook_id=NOTEBOOK,
        labels=labels,
        links=links,
        parsed=answer,
        sources=sources or SOURCES,
        now=NOW,
        new_id=new_id,
    )


def test_new_labels_and_links_are_created_for_an_empty_notebook() -> None:
    """The first run: auto labels after each other, auto links."""
    plan = run([], [], parsed(["Cells", "Energy"], {"s1": [0], "s2": [0, 1]}))

    assert [(l.name, l.position, l.origin) for l in plan.new_labels] == [
        ("Cells", 1, LabelOrigin.AUTO),
        ("Energy", 2, LabelOrigin.AUTO),
    ]
    by_name = {l.name: l.id for l in plan.new_labels}
    assert {(l.source_id, l.label_id) for l in plan.new_links} == {
        (S1, by_name["Cells"]),
        (S2, by_name["Cells"]),
        (S2, by_name["Energy"]),
    }
    assert all(l.origin is LabelOrigin.AUTO for l in plan.new_links)


def test_a_manual_label_with_the_same_name_is_reused_not_duplicated() -> None:
    """Any case: the student's label gets the links, nothing new is created."""
    mine = stored("cells", LabelOrigin.MANUAL)

    plan = run([mine], [], parsed(["Cells"]))

    assert plan.new_labels == []
    assert plan.new_links == [LabelLink(S1, mine.id, LabelOrigin.AUTO)]


def test_manual_links_and_labels_survive_a_run() -> None:
    """A manual link is not replaced; the run adds nothing to a full source."""
    mine = stored("Mine", LabelOrigin.MANUAL)
    other = stored("Other", LabelOrigin.MANUAL, 2)
    third = stored("Third", LabelOrigin.MANUAL, 3)
    fourth = stored("Fourth", LabelOrigin.MANUAL, 4)
    links = [LabelLink(S1, label.id, LabelOrigin.MANUAL) for label in (mine, other, third)]

    plan = run([mine, other, third, fourth], links, parsed(["Fourth"]))

    assert plan.new_links == []  # S1 already has three labels
    assert plan.delete_labels == []


def test_the_auto_links_of_the_covered_sources_are_replaced() -> None:
    """The old auto label is unlinked and, left empty, removed."""
    old = stored("Old")
    links = [LabelLink(S1, old.id, LabelOrigin.AUTO)]

    plan = run([old], links, parsed(["New"]))

    assert plan.unlink_auto_of == sorted([S1, S2, S3])
    assert plan.delete_labels == [old.id]
    assert [label.name for label in plan.new_labels] == ["New"]


def test_an_auto_label_still_used_by_another_source_stays() -> None:
    """A source outside the run keeps its links, so its label is not removed."""
    old = stored("Old")
    links = [LabelLink(S3, old.id, LabelOrigin.AUTO)]

    plan = run([old], links, parsed(["New"]), sources={"s1": S1})

    assert plan.delete_labels == []
    assert plan.unlink_auto_of == [S1]


def test_a_manual_link_keeps_an_auto_label_alive() -> None:
    """The student set the link by hand: the label is not an orphan."""
    old = stored("Old")
    links = [LabelLink(S1, old.id, LabelOrigin.MANUAL)]

    plan = run([old], links, parsed(["New"], {"s2": [0]}))

    assert plan.delete_labels == []


def test_an_old_auto_label_with_the_same_name_is_reused() -> None:
    """No delete and create of the same name."""
    old = stored("Cells")
    links = [LabelLink(S1, old.id, LabelOrigin.AUTO)]

    plan = run([old], links, parsed(["Cells"], {"s1": [0], "s2": [0]}))

    assert plan.delete_labels == [] and plan.new_labels == []
    assert {link.source_id for link in plan.new_links} == {S1, S2}


def test_a_notebook_never_holds_more_than_twelve_labels() -> None:
    """Room is what manual labels leave; the rest of the answer is dropped."""
    manual = [stored(f"Mine {n}", LabelOrigin.MANUAL, n) for n in range(1, 11)]
    answer = parsed(
        ["A", "B", "C", "D"], {"s1": [0, 1], "s2": [2, 3], "s3": [0]}
    )

    plan = run(manual, [], answer)

    assert [label.name for label in plan.new_labels] == ["A", "B"]
    assert {link.label_id for link in plan.new_links} <= {l.id for l in plan.new_labels}


def test_a_label_that_ends_up_without_a_link_is_not_created() -> None:
    """Every created label is used."""
    plan = run([], [], parsed(["Used", "Lost"], {"s1": [0], "s9": [1]}))

    assert [label.name for label in plan.new_labels] == ["Used"]


def test_ids_come_from_the_given_generator() -> None:
    """The plan is pure: ids and time are injected."""
    ids: Iterator[UUID] = iter([UUID(int=1), UUID(int=2)])

    plan = plan_labels(
        notebook_id=NOTEBOOK,
        labels=[],
        links=[],
        parsed=parsed(["A", "B"], {"s1": [0, 1]}),
        sources=SOURCES,
        now=NOW,
        new_id=lambda: next(ids),
    )

    assert [label.id for label in plan.new_labels] == [UUID(int=1), UUID(int=2)]
    assert all(label.created_at == NOW for label in plan.new_labels)
