"""The essay flow: prompt map, daily practice, idea fit, groups, gallery and slots.

The flow runs in one direction: the prompt map shows which prompts one essay can
answer, daily practice feeds the ideas bank, ideas are scored against the prompts
that still lack material, a draft written for a prompt group is reviewed for every
university of the group and forked per university, finished essays are compared
with others and finally dropped into the prompt slots of each university.
"""

import datetime as dt
import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

COMMON_APP: Final = "ca"
"""Owner key of the Common App personal statement prompts."""
COMMON_APP_WORD_LIMIT: Final = 650
COMMON_APP_PROMPTS: Final[tuple[str, ...]] = (
    "Some students have a background, identity, interest, or talent that is so "
    "meaningful they believe their application would be incomplete without it. If "
    "this sounds like you, then please share your story.",
    "The lessons we take from obstacles we encounter can be fundamental to later "
    "success. Recount a time when you faced a challenge, setback, or failure. How "
    "did it affect you, and what did you learn from the experience?",
    "Reflect on a time when you questioned or challenged a belief or idea. What "
    "prompted your thinking? What was the outcome?",
    "Reflect on something that someone has done for you that has made you happy or "
    "thankful in a surprising way. How has this gratitude affected or motivated you?",
    "Discuss an accomplishment, event, or realization that sparked a period of "
    "personal growth and a new understanding of yourself or others.",
    "Describe a topic, idea, or concept you find so engaging that it makes you lose "
    "all track of time. Why does it captivate you? What or who do you turn to when "
    "you want to learn more?",
    "Share an essay on any topic of your choice. It can be one you've already "
    "written, one that responds to a different prompt, or one of your own design.",
)
"""The seven Common App personal statement prompts (unchanged since 2023-24)."""

DELTAS: Final[dict[str, float]] = {
    "qwen/qwen3-embedding-4b": 0.39,
    "fake/embedding-v1": 0.55,
}
"""Largest cosine distance at which two prompts share a cluster, per model.

0.39 was tuned on the 42 prompts of the catalog (7 Common App, 35 supplements of
six universities) against 18 hand-labelled reusable pairs: complete linkage gives
precision 0.94 and recall 0.83 there (F1 0.88, the best of 0.22 to 0.45). The fake
model of development compares words, not meaning; 0.55 keeps its clusters small.
"""
DEFAULT_DELTA: Final = 0.39

PS_SLOT: Final = "ps"
"""Slot key of the personal statement; supplements are `supp:<position>`."""
MAX_GROUP: Final = 5
"""Universities one group draft may target (one review per university)."""
TOP_ESSAYS: Final = 10

PRACTICE_MAX: Final = 6000
PRACTICE_MIN_WORDS: Final = 30
PRACTICE_HISTORY: Final = 30
PRACTICE_THEMES: Final[dict[str, str]] = {
    "kitchen": "A smell from your family kitchen and the memory it opens.",
    "mistake": "A small mistake you still think about.",
    "object": "An ordinary object you would save from a fire, and why.",
    "street": "The street outside your home at six in the morning.",
    "argument": "An argument you lost and were glad to lose.",
    "teacher": "Something a teacher said that you did not understand until later.",
    "hands": "What your hands are good at.",
    "silence": "A moment when silence said more than words.",
    "first": "The first time you did something alone.",
    "map": "A place that is not on any map but matters to you.",
    "question": "A question you cannot stop asking.",
    "rule": "A rule you broke, or one you keep that nobody asked you to.",
    "sound": "A sound that means home.",
    "change": "Something you believed at twelve and no longer believe.",
    "stranger": "A conversation with a stranger.",
    "build": "Something you built, fixed or took apart.",
    "language": "A word in your language that has no translation.",
    "weather": "Describe today's weather as if it were your mood.",
    "photo": "A photograph that is missing from your family album.",
    "letter": "A letter to yourself in five years.",
    "work": "An hour of work nobody saw you do.",
}
"""Daily practice themes (English for the model; the web shows its own copy)."""

PracticeKey = Literal["imagery", "voice", "structure", "originality"]
PRACTICE_KEYS: Final[tuple[PracticeKey, ...]] = (
    "imagery",
    "voice",
    "structure",
    "originality",
)
MomentKind = Literal["surprising", "fresh", "earned"]
ParagraphRole = Literal["hook", "context", "turn", "evidence", "insight", "close"]
Strength = Literal["strong", "ok", "weak"]


def practice_streak(days: Iterable[dt.date], today: dt.date) -> int:
    """Consecutive practice days ending today, or yesterday when today is still open."""
    have = set(days)
    day = today if today in have else today - dt.timedelta(days=1)
    n = 0
    while day in have:
        n += 1
        day -= dt.timedelta(days=1)
    return n


def theme_for(day: dt.date) -> str:
    """The practice theme of a day: the same for every student, a new one daily."""
    keys = tuple(PRACTICE_THEMES)
    return keys[day.toordinal() % len(keys)]


def delta_for(model: str) -> float:
    """The cluster threshold of an embedding model."""
    return DELTAS.get(model, DEFAULT_DELTA)


def supp_slot(position: int) -> str:
    """The slot key of a supplemental prompt."""
    return f"supp:{position}"


def valid_slot(slot: str) -> bool:
    """`ps` or `supp:<non-negative position>`."""
    if slot == PS_SLOT:
        return True
    head, _, tail = slot.partition(":")
    return head == "supp" and tail.isdigit() and len(tail) <= 3


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """1 minus the cosine similarity; 1 when either vector is zero."""
    norm = math.sqrt(math.sumprod(a, a) * math.sumprod(b, b))
    if norm == 0:
        return 1.0
    return 1.0 - math.sumprod(a, b) / norm


def _pair_distances(
    vectors: Sequence[Sequence[float]], owners: Sequence[str]
) -> dict[tuple[int, int], float]:
    """Cosine distances of every pair of vectors with different owners."""
    dist: dict[tuple[int, int], float] = {}
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            if owners[i] != owners[j]:
                dist[(i, j)] = cosine_distance(vectors[i], vectors[j])
    return dist


def cluster(
    vectors: Sequence[Sequence[float]], owners: Sequence[str], delta: float
) -> list[list[int]]:
    """Complete-linkage clusters: every two members are at most `delta` apart.

    Two prompts of one owner (a university, or the Common App) never share a
    cluster: one essay cannot answer two prompts of the same application. Pairs are
    merged closest first, so the result is deterministic. Members of a cluster and
    the clusters are in input order.
    """
    n = len(vectors)
    dist = _pair_distances(vectors, owners)
    root = list(range(n))
    members: dict[int, list[int]] = {i: [i] for i in range(n)}

    def far(x: int, y: int) -> bool:
        key = (x, y) if x < y else (y, x)
        return key not in dist or dist[key] > delta

    for (i, j), d in sorted(dist.items(), key=lambda kv: (kv[1], kv[0])):
        if d > delta:
            break
        ri, rj = root[i], root[j]
        if ri == rj or any(far(x, y) for x in members[ri] for y in members[rj]):
            continue
        keep, gone = min(ri, rj), max(ri, rj)
        for x in members[gone]:
            root[x] = keep
        members[keep] = sorted(members[keep] + members.pop(gone))
    return [members[k] for k in sorted(members)]


def nearest(vectors: Sequence[Sequence[float]], owners: Sequence[str]) -> list[float]:
    """Distance of each vector to the closest vector of another owner (1 if none)."""
    out = [1.0] * len(vectors)
    for i, a in enumerate(vectors):
        for j, b in enumerate(vectors):
            if owners[i] != owners[j]:
                out[i] = min(out[i], cosine_distance(a, b))
    return out


def fit_score(distance: float, delta: float) -> int:
    """0 to 100: how well a text fits a prompt, scaled to the model's threshold.

    Half the threshold or closer is 100; twice the threshold or farther is 0.
    """
    low, high = delta / 2, delta * 2
    share = (high - distance) / (high - low)
    return round(100 * min(1.0, max(0.0, share)))


@dataclass(frozen=True, slots=True)
class PromptRef:
    """One prompt of the map: a Common App prompt or a university supplement."""

    key: str
    institution_id: UUID | None
    institution_name: str
    position: int
    prompt: str
    word_limit: int | None
    limit_unit: str = "words"
    required: bool = True
    in_list: bool = False

    @property
    def owner(self) -> str:
        """The application the prompt belongs to."""
        return COMMON_APP if self.institution_id is None else str(self.institution_id)

    @property
    def slot(self) -> str:
        """The slot key it fills in the final matching table."""
        return PS_SLOT if self.institution_id is None else supp_slot(self.position)


def prompt_key(institution_id: UUID | None, position: int) -> str:
    """`ca:<n>` or `<institution id>:<position>`."""
    owner = COMMON_APP if institution_id is None else str(institution_id)
    return f"{owner}:{position}"


def common_app_refs() -> list[PromptRef]:
    """The seven Common App prompts as map entries (position 0 to 6)."""
    return [
        PromptRef(
            key=prompt_key(None, i),
            institution_id=None,
            institution_name="Common App",
            position=i,
            prompt=text,
            word_limit=COMMON_APP_WORD_LIMIT,
        )
        for i, text in enumerate(COMMON_APP_PROMPTS)
    ]


@dataclass(frozen=True, slots=True)
class PromptGroup:
    """Prompts one essay can answer; `kind` is common, shared or unique."""

    key: str
    kind: Literal["common", "shared", "unique"]
    prompts: tuple[PromptRef, ...]
    spread: float
    """Largest distance inside the group; for a unique prompt, its nearest other."""


LABEL_MAX: Final = 60
LABEL_LOCALES: Final = ("ru", "en", "uz")


def members_hash(prompts: Sequence[PromptRef]) -> str:
    """A digest of the member prompts of a group: its stored label is valid for it."""
    raw = "\n".join(sorted(f"{p.key}\t{p.prompt}" for p in prompts))
    return hashlib.sha256(raw.encode()).hexdigest()


def fallback_label(prompts: Sequence[PromptRef]) -> str:
    """A label made of the first words of the first prompt (no model needed)."""
    words = prompts[0].prompt.split()[:6]
    text = " ".join(words).rstrip(",.;:?!")
    return text[:LABEL_MAX] or prompts[0].institution_name


@dataclass(frozen=True, slots=True)
class GroupLabel:
    """The short human name of a group in each locale, generated once and stored."""

    members_hash: str
    ru: str
    en: str
    uz: str
    model: str = ""

    def of(self, locale: str) -> str:
        """The label in the locale (English when the locale has none)."""
        return {"ru": self.ru, "uz": self.uz}.get(locale) or self.en


@dataclass(frozen=True, slots=True)
class PromptMap:
    """The groups of the map and the threshold that made them."""

    model: str
    delta: float
    clustered: bool
    groups: tuple[PromptGroup, ...]


def build_map(
    refs: Sequence[PromptRef],
    vectors: Sequence[Sequence[float]] | None,
    *,
    model: str,
) -> PromptMap:
    """Group the prompts; without vectors every prompt stands alone."""
    delta = delta_for(model)
    owners = [r.owner for r in refs]
    if vectors is None:
        clusters = [[i] for i in range(len(refs))]
        near = [1.0] * len(refs)
    else:
        clusters = cluster(vectors, owners, delta)
        near = nearest(vectors, owners)
    groups: list[PromptGroup] = []
    for members in clusters:
        prompts = tuple(refs[i] for i in members)
        common = any(p.institution_id is None for p in prompts)
        if len(members) > 1 and vectors is not None:
            spread = max(
                cosine_distance(vectors[a], vectors[b])
                for a in members
                for b in members
                if a < b
            )
        else:
            spread = near[members[0]]
        kind: Literal["common", "shared", "unique"] = (
            "common" if common else "shared" if len(members) > 1 else "unique"
        )
        groups.append(PromptGroup(prompts[0].key, kind, prompts, round(spread, 4)))
    order = {"common": 0, "shared": 1, "unique": 2}
    groups.sort(
        key=lambda g: (
            order[g.kind],
            -len(g.prompts) if g.kind == "shared" else 0,
            -g.spread if g.kind == "unique" else 0,
            g.key,
        )
    )
    return PromptMap(model, delta, vectors is not None, tuple(groups))


@dataclass(frozen=True, slots=True)
class StoredIdeaFit:
    """A cached idea fit: scored prompt keys valid for one prompt-map version."""

    version: str
    available: bool
    model: str
    delta: float
    items: tuple[tuple[str, float, int], ...]
    """`(prompt key, distance, score)`, best first."""


@dataclass(frozen=True, slots=True)
class PromptTarget:
    """A prompt a draft answers; the text is copied so the draft keeps it."""

    institution_id: UUID | None
    position: int
    prompt: str
    word_limit: int | None = None

    @property
    def key(self) -> str:
        """Return the stable key of the prompt this target answers."""
        return prompt_key(self.institution_id, self.position)


@dataclass(frozen=True, slots=True)
class PracticeScore:
    """One creative-writing dimension, 0 to 5."""

    key: str
    score: int
    comment: str


@dataclass(frozen=True, slots=True)
class PracticeEvaluation:
    """The evaluation of one practice entry; never a rewrite."""

    summary: str
    scores: tuple[PracticeScore, ...]
    praise: tuple[str, ...]
    try_next: tuple[str, ...]
    idea_seeds: tuple[str, ...]
    locale: str = ""
    """The language of the feedback; an evaluation is reused only for the same one."""


@dataclass(slots=True)
class PracticeEntry:
    """A day's free writing on the theme of the day."""

    id: UUID
    student_id: UUID
    day: dt.date
    theme: str
    body: str
    evaluation: PracticeEvaluation | None = None
    model: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class GalleryEntry:
    """An essay version a student published to other students, without a name."""

    id: UUID
    essay_id: UUID
    student_id: UUID
    version: int
    published_at: dt.datetime | None = None
    # Frozen at publish; `None` for entries published before the freeze.
    title: str | None = None
    prompt_text: str | None = None
    word_limit: int | None = None
    targets: "tuple[PromptTarget, ...]" = ()


@dataclass(frozen=True, slots=True)
class SlotAssignment:
    """An essay placed into one prompt slot of one university."""

    student_id: UUID
    institution_id: UUID
    slot: str
    essay_id: UUID


@dataclass(frozen=True, slots=True)
class ParagraphRead:
    """What one paragraph does and reveals about the writer; 1-based."""

    paragraph: int
    role: str
    reveals: str
    strength: str


@dataclass(frozen=True, slots=True)
class Moment:
    """A so-what moment: a line that lands an insight."""

    paragraph: int
    quote: str
    kind: str


@dataclass(frozen=True, slots=True)
class DeepRead:
    """Paragraph by paragraph reading, uniqueness and the one fix that matters most."""

    paragraphs: tuple[ParagraphRead, ...]
    uniqueness: int
    uniqueness_note: str
    tropes: tuple[str, ...]
    moments: tuple[Moment, ...]
    fix_paragraph: int
    fix_dimension: str
    fix_problem: str
    fix_try: str
