"""NB-3: renaming, pinning and configuring a notebook."""

from typing import Any

from app.modules.notebooks.domain.entities import ChatConfig, Notebook
from app.modules.notebooks.domain.enums import ChatLanguage, ChatLength, ChatStyle
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import NOW, make_notebook
from tests.fakes.clock import FixedClock

import pytest


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook with an automatic title and emoji."""
    return await make_notebook(
        uow_factory, student.user_id, title="Untitled notebook", emoji="📄"
    )


async def _stored(uow_factory: UowFactory, notebook: Notebook) -> Notebook:
    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
    assert stored is not None
    return stored


async def test_manual_title_is_trimmed_saved_and_stops_automatic_titles(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-3: a rename sets `title_auto=False` and touches `updated_at`."""
    clock.advance(minutes=5)

    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"title": "  Photosynthesis  "}
    )

    stored = await _stored(uow_factory, notebook)
    assert stored == result
    assert result.title == "Photosynthesis"
    assert result.title_auto is False
    assert result.emoji_auto is True
    assert result.updated_at == clock.now() != NOW


async def test_title_limits_are_1_to_120_characters(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: 120 characters pass, 121 and blank titles do not."""
    ok = await lifecycle.update_notebook.execute(
        student, notebook.id, {"title": "t" * 120}
    )
    assert len(ok.title) == 120

    for bad in ("t" * 121, "", "   "):
        with pytest.raises(InvalidOptionsError) as caught:
            await lifecycle.update_notebook.execute(
                student, notebook.id, {"title": bad}
            )
        assert caught.value.params == {"field": "title"}


async def test_emoji_is_set_and_stops_automatic_emoji(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: a chosen emoji sets `emoji_auto=False`."""
    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"emoji": "🧬"}
    )

    assert result.emoji == "🧬"
    assert result.emoji_auto is False
    assert result.title_auto is True


async def test_emoji_none_clears_it_for_good(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: `emoji: null` removes the emoji and the AI will not add one again."""
    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"emoji": None}
    )

    stored = await _stored(uow_factory, notebook)
    assert stored.emoji is None
    assert stored.emoji_auto is False
    assert result == stored


async def test_emoji_over_16_characters_is_refused(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: the emoji is at most 16 characters; a non-string is refused."""
    for bad in ("x" * 17, 5):
        with pytest.raises(InvalidOptionsError):
            await lifecycle.update_notebook.execute(
                student, notebook.id, {"emoji": bad}
            )


async def test_pinning_and_unpinning(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: `pinned` toggles; only a real boolean is accepted."""
    pinned = await lifecycle.update_notebook.execute(
        student, notebook.id, {"pinned": True}
    )
    unpinned = await lifecycle.update_notebook.execute(
        student, notebook.id, {"pinned": False}
    )

    assert pinned.pinned is True
    assert unpinned.pinned is False
    for bad in (1, "yes", None):
        with pytest.raises(InvalidOptionsError):
            await lifecycle.update_notebook.execute(
                student, notebook.id, {"pinned": bad}
            )


async def test_chat_config_is_validated_and_saved(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: style, prompt, length and language are stored as a typed config."""
    result = await lifecycle.update_notebook.execute(
        student,
        notebook.id,
        {
            "chat_config": {
                "style": "custom",
                "custom_prompt": "Explain like I am ten",
                "length": "shorter",
                "language": "uz",
            }
        },
    )

    stored = await _stored(uow_factory, notebook)
    assert stored.chat_config == result.chat_config
    assert result.chat_config == ChatConfig(
        style=ChatStyle.CUSTOM,
        custom_prompt="Explain like I am ten",
        length=ChatLength.SHORTER,
        language=ChatLanguage.UZ,
    )


async def test_custom_style_without_a_prompt_is_allowed(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: the prompt may be filled in later."""
    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"style": "custom"}}
    )

    assert result.chat_config.style is ChatStyle.CUSTOM
    assert result.chat_config.custom_prompt is None


async def test_chat_config_keeps_the_fields_that_are_not_sent(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: a partial config changes only the given fields."""
    await lifecycle.update_notebook.execute(
        student,
        notebook.id,
        {"chat_config": {"length": "longer", "custom_prompt": "Be brief"}},
    )

    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"language": "ru"}}
    )

    assert result.chat_config.language is ChatLanguage.RU
    assert result.chat_config.length is ChatLength.LONGER
    assert result.chat_config.custom_prompt == "Be brief"


async def test_chat_config_accepts_a_config_object_and_a_cleared_prompt(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: a `ChatConfig` works too; `custom_prompt: None` clears the prompt."""
    await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"custom_prompt": "Be brief"}}
    )

    result = await lifecycle.update_notebook.execute(
        student,
        notebook.id,
        {"chat_config": ChatConfig(style=ChatStyle.LEARNING_GUIDE)},
    )
    cleared = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"custom_prompt": None}}
    )

    assert result.chat_config.style is ChatStyle.LEARNING_GUIDE
    assert result.chat_config.custom_prompt == "Be brief"
    assert cleared.chat_config.custom_prompt is None


@pytest.mark.parametrize(
    "config",
    [
        {"custom_prompt": "p" * 1001},
        {"style": "pirate"},
        {"length": "huge"},
        {"language": "klingon"},
        {"unknown": 1},
        "default",
        None,
    ],
)
async def test_invalid_chat_config_is_refused(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    config: Any,
) -> None:
    """NB-3: bad values, unknown keys and non-objects raise `InvalidOptionsError`."""
    with pytest.raises(InvalidOptionsError) as caught:
        await lifecycle.update_notebook.execute(
            student, notebook.id, {"chat_config": config}
        )

    assert caught.value.params == {"field": "chat_config"}
    assert (await _stored(uow_factory, notebook)).chat_config == ChatConfig()


async def test_prompt_of_exactly_1000_characters_is_allowed(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: the custom prompt limit is 1000 characters."""
    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"custom_prompt": "p" * 1000}}
    )

    assert result.chat_config.custom_prompt == "p" * 1000


async def test_goal_is_trimmed_saved_and_kept_when_other_settings_change(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-7: the goal is stored trimmed and survives a later partial config."""
    await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": "  Pass the exam \n"}}
    )

    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"length": "shorter"}}
    )

    assert result.chat_config.goal == "Pass the exam"
    assert (await _stored(uow_factory, notebook)).chat_config.goal == "Pass the exam"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_a_blank_goal_clears_it(
    lifecycle: NotebooksLifecycleServices,
    student: Actor,
    notebook: Notebook,
    blank: str,
) -> None:
    """NB-7: an empty goal means no goal; so does null."""
    await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": "Pass the exam"}}
    )

    cleared = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": blank}}
    )
    await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": "Again"}}
    )
    nulled = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": None}}
    )

    assert cleared.chat_config.goal is None
    assert nulled.chat_config.goal is None


async def test_goal_of_exactly_300_characters_is_allowed_and_301_is_not(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-7: the goal limit is 300 characters."""
    result = await lifecycle.update_notebook.execute(
        student, notebook.id, {"chat_config": {"goal": "g" * 300}}
    )

    with pytest.raises(InvalidOptionsError) as caught:
        await lifecycle.update_notebook.execute(
            student, notebook.id, {"chat_config": {"goal": "g" * 301}}
        )

    assert result.chat_config.goal == "g" * 300
    assert caught.value.params == {"field": "chat_config"}


@pytest.mark.parametrize("goal", [5, ["exam"], {"a": 1}])
async def test_a_goal_that_is_not_text_is_refused(
    lifecycle: NotebooksLifecycleServices,
    student: Actor,
    notebook: Notebook,
    goal: Any,
) -> None:
    """NB-7: only text (or null) is a goal."""
    with pytest.raises(InvalidOptionsError):
        await lifecycle.update_notebook.execute(
            student, notebook.id, {"chat_config": {"goal": goal}}
        )


async def test_several_fields_change_together(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: one PATCH may carry every field."""
    result = await lifecycle.update_notebook.execute(
        student,
        notebook.id,
        {"title": "Cells", "emoji": "🔬", "pinned": True, "chat_config": {}},
    )

    assert (result.title, result.emoji, result.pinned) == ("Cells", "🔬", True)


async def test_unknown_key_is_refused(
    lifecycle: NotebooksLifecycleServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: only title, emoji, pinned and chat_config can be changed."""
    for key in ("summary", "owner_id", "deleted_at", "title_auto"):
        with pytest.raises(InvalidOptionsError) as caught:
            await lifecycle.update_notebook.execute(student, notebook.id, {key: "x"})
        assert caught.value.params == {"field": key}


async def test_nothing_is_saved_when_one_of_the_changes_is_invalid(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the update is all or nothing."""
    with pytest.raises(InvalidOptionsError):
        await lifecycle.update_notebook.execute(
            student, notebook.id, {"title": "Fine", "pinned": "maybe"}
        )

    assert await _stored(uow_factory, notebook) == notebook


async def test_empty_changes_leave_the_notebook_untouched(
    lifecycle: NotebooksLifecycleServices,
    student: Actor,
    notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-3: a PATCH without fields is not an edit."""
    clock.advance(hours=1)

    result = await lifecycle.update_notebook.execute(student, notebook.id, {})

    assert result == notebook
    assert result.updated_at == NOW


async def test_another_students_notebook_cannot_be_changed(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-3: a foreign notebook answers 404 and stays as it was."""
    theirs = await make_notebook(uow_factory, other_student.user_id)

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.update_notebook.execute(student, theirs.id, {"title": "Mine"})

    assert await _stored(uow_factory, theirs) == theirs


async def test_deleted_notebook_cannot_be_changed(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: a soft-deleted notebook answers 404."""
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.update_notebook.execute(student, gone.id, {"pinned": True})
