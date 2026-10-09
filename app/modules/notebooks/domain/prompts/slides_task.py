"""The task block of a slide deck (§ 3.4.6): an explicit outline for a good deck.

The model gets the shape of the deck (title, agenda, sections, one idea per slide, a
summary), the text budget of each slide for the chosen format, when to use which
layout, and the citation rules. The common Studio system prompt sets the language.
"""

from dataclasses import dataclass
from typing import Final, Literal

from app.modules.notebooks.domain.prompts.common import focus_clause

SlideFormat = Literal["presenter", "detailed"]


@dataclass(frozen=True, slots=True)
class FormatGuide:
    """What one format asks of a content slide."""

    bullets: int
    words: int
    body: str
    notes: str


GUIDES: Final = {
    "presenter": FormatGuide(
        bullets=5,
        words=12,
        body="`body` is null (a section slide may have one short sentence)",
        notes=(
            "`notes` are the speaker's words for the slide: 2 to 4 full sentences "
            "that explain and add an example or detail that is not on the slide"
        ),
    ),
    "detailed": FormatGuide(
        bullets=6,
        words=20,
        body=(
            "`body` is one paragraph of at most 45 words that explains the idea, so "
            "the deck can be read without a speaker"
        ),
        notes="`notes` are 1 or 2 sentences for the presenter",
    ),
}

_TEMPLATE: Final = """\
Create a slide deck from the sources: about {count} slides (between {low} and \
{high}). Format: {format_name}.

Deck outline, in this order:
1. A "title" slide: `title` = the topic of the deck (at most 8 words); `bullets` \
empty; `notes` = how to open the talk. Also fill the deck's `title` (the same topic) \
and `subtitle` (one short line: the subject, the scope or the audience).
2. An "agenda" slide: `title` = the word for "Agenda" in the language of the deck; \
`bullets` = the names of the parts of the deck, 3 to 6, in the order they come.
3. The content, part by part, in the order the sources present it. Use the sources \
in their order (S1 first, then S2, ...), and give every source at least one slide \
when it has relevant content. In decks of 10 or more slides, open each part with a \
"section" slide (a short `title`, `body` one sentence).
4. A "summary" slide last: `title` such as "Key takeaways"; 3 to 5 `bullets`, each \
one takeaway a student should remember.

Every content slide develops ONE idea, named by a specific `title` (at most 8 words, \
no numbering, no final period; never just "Introduction" or "Slide 3"). Do not repeat \
a slide or say the same thing twice.

Text budget of a content slide ({format_name}): at most {bullets} `bullets`, each at \
most {words} words. A bullet is a short phrase or one sentence: concrete facts, \
terms, numbers, dates and names from the sources, not vague statements. {body}. \
{notes}.

Choose the layout that fits the content, and use at least three layouts:
- "bullets": a list of points.
- "two_columns": a comparison of two things; `left` and `right` each have a \
`heading` (at most 4 words) and at most 4 `bullets`.
- "table": facts with rows and columns: 2 to 4 `columns`, at most 6 `rows`, every row \
has one short cell per column.
- "quote": a key sentence copied word for word from the sources (translated only if \
the deck is in another language) in `quote.text`, at most 40 words, with \
`quote.attribution` = its author or the source title; at most one quote slide.
- "section", "agenda", "title", "summary" as described above.
Leave every field the layout does not use null.

Plain text only: no Markdown (no **, #, `), no bullet characters or numbering at the \
start of a bullet, no citation markers in any text. Write formulas and code as plain \
text with Unicode symbols (x², H₂O, a ≠ b), never LaTeX.

`refs`: every slide except the title, agenda and section slides cites 1 to 3 \
passages that support it, as labels copied from <sources> such as "S1:P4". A slide \
must not say anything its passages do not support.

`visual_hint`: a short description of a diagram, chart or picture that would help \
on this slide (for example "Timeline 1914-1918 with four battles"), never a URL; \
null when none fits."""


def slides_task(
    *, count: int, tolerance: int, fmt: SlideFormat, prompt: str | None
) -> str:
    """The task block for a deck of about `count` slides in the format `fmt`."""
    guide = GUIDES[fmt]
    task = _TEMPLATE.format(
        count=count,
        low=max(count - tolerance, 3),
        high=count + tolerance,
        format_name=f"{fmt} slides" if fmt == "presenter" else "detailed deck",
        bullets=guide.bullets,
        words=guide.words,
        body=guide.body[0].upper() + guide.body[1:],
        notes=guide.notes[0].upper() + guide.notes[1:],
    )
    return task + focus_clause(prompt)
