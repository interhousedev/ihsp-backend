"""Argument models of the test tools (limits of the quiz kind)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Prompt = Annotated[str, Field(min_length=1, max_length=400)]
Explanation = Annotated[
    str,
    Field(min_length=1, max_length=2000, description="Why the right answer is right."),
]


class TestOption(BaseModel):
    """One answer option."""

    id: str = Field(
        min_length=1,
        max_length=20,
        description="Your id for the option. True/false: `true` and `false`.",
    )
    text: str = Field(min_length=1, max_length=200)


# At least 2: the quiz rules check it after the guard, with a clear reason.
Options = Annotated[list[TestOption], Field(min_length=1, max_length=6)]
Correct = Annotated[
    list[str],
    Field(
        min_length=1,
        max_length=6,
        description="Ids of the right options: one for single and true_false, "
        "at least two (not all) for multiple.",
    ),
]
QuestionKind = Literal["single", "multiple", "true_false"]
Hint = Annotated[str, Field(max_length=200)]
Topic = Annotated[str, Field(max_length=60)]


class NewQuestion(BaseModel):
    """A question to add."""

    type: QuestionKind
    prompt: Prompt
    options: Options
    correct: Correct
    explanation: Explanation
    hint: Hint | None = None
    topic: Topic | None = None


class QuestionChange(BaseModel):
    """Changes of one question; what is left out stays."""

    id: str = Field(min_length=1, max_length=40, description="Id from get_test.")
    type: QuestionKind | None = None
    prompt: Prompt | None = None
    options: Options | None = None
    correct: Correct | None = None
    explanation: Explanation | None = None
    hint: Hint | None = None
    topic: Topic | None = None


def question_dicts(items: list[Any]) -> list[dict[str, Any]]:
    """Plain dicts without the fields that were left out."""
    return [item.model_dump(exclude_none=True) for item in items]
