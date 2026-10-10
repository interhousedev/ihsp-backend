"""Flash card outputs (§ 3.4.3): front/back cards with a topic, a hint and refs."""

import unicodedata
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    clip_chars,
    dump_options,
    expect_options,
    fit_text,
    parse_options,
    require_list,
    validate_items,
)
from app.modules.notebooks.domain.artifacts.refs import (
    build_refs_index,
    cites_honestly,
    keep_items_with_refs,
    valid_refs,
)
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.common import difficulty_clause, focus_clause

from pydantic import BaseModel, Field

SCHEMA_NAME: Final = "nb_flashcards"
CARD_COUNTS: Final = {"fewer": 10, "standard": 20, "more": 35}
# About 300 tokens per card in Russian or Uzbek (Cyrillic and formulas tokenize
# worse than English), plus room for the title.
MAX_TOKENS: Final = {"fewer": 3500, "standard": 6500, "more": 11000}
FRONT_MAX_CHARS: Final = 160
BACK_MAX_CHARS: Final = 300
HINT_MAX_CHARS: Final = 200
TOPIC_MAX_CHARS: Final = 60


class FlashcardsOptions(CommonOptions):
    """`FlashcardsOptions` of § 4.4."""

    count: Literal["fewer", "standard", "more"] = "standard"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class CardOut(BaseModel):
    """One card of the model's answer."""

    id: str = Field(description="c1, c2, ...")
    front: str = Field(description="a question or a term, at most 160 characters")
    back: str = Field(description="a short answer, at most 300 characters")
    hint: str | None = Field(description="optional; must not give the answer away")
    topic: str | None = Field(description="a 1-3 word group name")
    refs: list[str] = Field(description='passage labels such as "S1:P3"')


class FlashcardsOutput(BaseModel):
    """The JSON of a flash card set (``nb_flashcards``)."""

    title: str
    cards: list[CardOut]


@dataclass(slots=True)
class _Card:
    front: str
    back: str
    hint: str | None
    topic: str | None
    refs: list[str]
    trusted: bool = True  # valid refs, or honestly none (see `cites_honestly`)


def _card_input(raw: Any) -> Any:
    """Fill the fields a model may leave out; ids are rewritten later anyway."""
    if not isinstance(raw, dict):
        return raw
    card = dict(raw)
    card["id"] = ""
    card.setdefault("hint", None)
    card.setdefault("topic", None)
    if not isinstance(card.get("refs"), list):
        card["refs"] = []
    return card


def _tidy(item: CardOut, refs: list[str]) -> _Card | None:
    """Trim the texts; a card without a front or a back is dropped."""
    front = fit_text(item.front, chars=FRONT_MAX_CHARS)
    back = fit_text(item.back, chars=BACK_MAX_CHARS)
    if not front or not back:
        return None
    return _Card(
        front=front,
        back=back,
        hint=fit_text(item.hint, chars=HINT_MAX_CHARS) or None,
        topic=fit_text(item.topic, chars=TOPIC_MAX_CHARS) or None,
        refs=refs,
        trusted=cites_honestly(item.refs, refs),
    )


def front_key(front: str) -> str:
    """Normalise a front for duplicate detection.

    Unicode-normalised, case-folded, punctuation removed (symbols such as ``+`` ``=``
    ``^`` stay, so ``x+1`` and ``x-1`` are different cards), spaces collapsed.
    """
    folded = unicodedata.normalize("NFKC", front).casefold()
    kept = "".join(ch for ch in folded if not unicodedata.category(ch).startswith("P"))
    return " ".join(kept.split())


def _dedupe(cards: list[_Card]) -> list[_Card]:
    """Keep the first card of every normalised front."""
    seen: set[str] = set()
    unique: list[_Card] = []
    for card in cards:
        key = front_key(card.front)
        if key not in seen:
            seen.add(key)
            unique.append(card)
    return unique


class FlashcardsHandler:
    """Options, prompt, schema and validation of flash card sets."""

    kind = ArtifactKind.FLASHCARDS
    schema_name = SCHEMA_NAME

    def parse_options(self, raw: dict[str, Any]) -> FlashcardsOptions:
        """Validate the request's options."""
        return parse_options(FlashcardsOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, FlashcardsOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """Only reports have a format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """2 000 / 3 500 / 6 000 tokens for fewer / standard / more cards."""
        return MAX_TOKENS[expect_options(options, FlashcardsOptions).count]

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict JSON schema of the output."""
        return to_strict_schema(FlashcardsOutput)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task (§ 3.4.3) plus the student's focus."""
        opts = expect_options(options, FlashcardsOptions)
        return (
            f"Create {CARD_COUNTS[opts.count]} flash cards that help a student"
            " memorize and understand the topic of the sources."
            f" {difficulty_clause(opts.difficulty)} Each card is atomic and"
            " self-contained: the front is one question or one term (at most 160"
            " characters), the back is a short, complete answer (at most 300"
            " characters) that a student can check themselves against; Markdown"
            " inline formatting and `$formula$` are allowed. Never ask what a"
            " heading says or what 'the source' contains; ask about the subject"
            " itself. No duplicates, no 'see above', no 'all of the above'. `topic`"
            " is a 1-3 word group name. `hint` is optional and must not give the"
            " answer away. Cover the sources evenly, then add the standard facts of"
            " the topic a student needs."
            f"{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Flash cards: <notebook>``."""
        return clip_chars(f"Flash cards: {notebook_title}", ARTIFACT_TITLE_MAX_CHARS)

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Dedupe, trim, resolve refs, cap the count and renumber the cards."""
        requested = CARD_COUNTS[expect_options(options, FlashcardsOptions).count]
        problems: list[str] = []
        items = validate_items(
            CardOut,
            [_card_input(raw) for raw in require_list(data, "cards")],
            problems,
            "card",
        )
        tidied = (_tidy(item, valid_refs(item.refs, ctx.pack)) for item in items)
        cards = _dedupe([card for card in tidied if card is not None])
        if not cards:
            raise OutputInvalidError(problems or ["`cards` has no usable card"])
        cards = keep_items_with_refs(cards, lambda c: c.trusted, requested)
        cards = cards[:requested]
        title = fit_text(data.get("title"), chars=ARTIFACT_TITLE_MAX_CHARS)
        content = {
            "title": title or "Flash cards",
            "cards": [
                {
                    "id": f"c{number}",
                    "front": card.front,
                    "back": card.back,
                    "hint": card.hint,
                    "topic": card.topic,
                    "refs": card.refs,
                }
                for number, card in enumerate(cards, start=1)
            ],
        }
        return ProcessedOutput(
            title=str(content["title"]),
            content=content,
            refs_index=build_refs_index((card.refs for card in cards), ctx.pack),
        )


HANDLER: ArtifactHandler = FlashcardsHandler()
