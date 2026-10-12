r"""Eval harness for AI slide decks: generate decks from sample sources, write HTML.

The samples (`tests/notebooks/fixtures/slides/sources/`) go through the same path as
in production: the real extractors (PDF, DOCX, TXT in UTF-8 and Windows-1251), the
chunker, the Studio context builder, the prompt and schema of the `slides` kind, one
repair call when the answer breaks the rules, and the kind's validation. A revise
case then rewrites two slides of the English deck. Each case writes to
`eval/out/slides/<case>/` (git-ignored):

- `deck.html`  the deck as slides plus a review panel (sources, notes) per slide;
  light/dark toggle, print to PDF gives one slide per page;
- `deck.json`  the stored content and `refs_index`;
- `raw-1.json` (and `raw-2.json` after a repair)  the model's answers;
- `prompt.txt` the system prompt, the task and the `<sources>` block.

`eval/out/slides/index.html` links the decks of the last run.

Usage (from the repo root):

    # real model (needs IHSP_OPENROUTER__API_KEY and IHSP_OPENROUTER__MODE=real,
    # e.g. in a git-ignored env file):
    IHSP_ENV_FILE="materials/dev.env,?materials/dev-keys/secrets.env" \
        uv run python scripts/nb_eval_slides.py
    # one case, or several:
    uv run python scripts/nb_eval_slides.py --case ru_history --case uz_temur
    # without a key (deterministic fake model), or forcing it:
    uv run python scripts/nb_eval_slides.py --fake
    # re-run validation and HTML on the saved answers, without calling the model:
    uv run python scripts/nb_eval_slides.py --replay
    # copy the final answers into the test fixtures (recorded realistic outputs):
    uv run python scripts/nb_eval_slides.py --replay --record

Cost: about 4 model calls (3 decks and 1 revision), usually under 0.10 USD.
"""

import argparse
import asyncio
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway  # noqa: E402
from app.modules.ai.infrastructure.gateway_factory import (  # noqa: E402
    make_llm_gateway,
)
from app.modules.notebooks.application.context_builder import (  # noqa: E402
    ContextBuilder,
)
from app.modules.notebooks.application.llm import NotebookLlm  # noqa: E402
from app.modules.notebooks.domain.artifacts.handler import (  # noqa: E402
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.slides import (  # noqa: E402
    HANDLER,
    SlidesOptions,
)
from app.modules.notebooks.domain.artifacts.slides_shape import (  # noqa: E402
    uncited,
)
from app.modules.notebooks.domain.context import ContextPack  # noqa: E402
from app.modules.notebooks.domain.errors import OutputInvalidError  # noqa: E402
from app.modules.notebooks.domain.language import (  # noqa: E402
    detect_language,
    resolve_language,
)
from app.modules.notebooks.domain.prompts.slides_revise import (  # noqa: E402
    SLIDES_REVISE_SCHEMA_NAME,
    merge_revised,
    revise_schema,
    revise_system_prompt,
    revise_user_message,
)
from app.modules.notebooks.domain.prompts.studio import (  # noqa: E402
    repair_message,
    studio_system_prompt,
)
from app.modules.notebooks.domain.sources_block import (  # noqa: E402
    render_sources_block,
)
from app.modules.notebooks.ports.unit_of_work import (  # noqa: E402
    NotebooksUnitOfWork,
)
from app.settings import Settings, load_settings  # noqa: E402
from app.shared.ai_tasks import AiTask  # noqa: E402
from app.shared.ids import new_id  # noqa: E402
from scripts.nb_eval_html import deck_html, index_html  # noqa: E402
from tests.notebooks.fixtures.slides import (  # noqa: E402
    RECORDED_DIR,
    SAMPLES,
    MemoryPassages,
    MemoryUow,
    stored,
)

OUT = BACKEND / "eval" / "out" / "slides"


@dataclass(frozen=True)
class Case:
    """One deck to generate: sample sources, options and an optional focus."""

    name: str
    sources: tuple[str, ...]
    options: dict[str, Any]
    prompt: str | None = None


CASES = {
    case.name: case
    for case in (
        Case("ru_history", ("peter_reforms", "peter_dates"), {"length": "default"}),
        Case(
            "uz_temur",
            ("amir_temur",),
            {"length": "short", "format": "detailed"},
        ),
        Case(
            "en_multi",
            ("industrial_revolution", "factory_acts"),
            {"length": "default"},
            prompt="for grade 9, include the dates",
        ),
    )
}
REVISE_OF = "en_multi"
REVISE_CHANGES = (
    (2, "Turn this slide into a two-column comparison: before and after."),
    (4, "Shorter: at most three bullets, and add one concrete date."),
)


@dataclass
class Run:
    """What one case produced."""

    name: str
    answers: list[dict[str, Any]] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    problems: list[list[str]] = field(default_factory=list)
    output: ProcessedOutput | None = None
    language: str = ""
    model: str = ""


def _llm(settings: Settings, fake: bool) -> NotebookLlm:
    """The real gateway when configured (and not `--fake`), else the fake one."""
    if fake or settings.openrouter.mode != "real":
        return NotebookLlm(FakeLlmGateway(), settings)
    return NotebookLlm(make_llm_gateway(settings), settings)


async def _pack(case: Case, settings: Settings) -> ContextPack:
    sources, passages = stored(case.sources)
    uow = cast(NotebooksUnitOfWork, MemoryUow(MemoryPassages(passages)))
    return await ContextBuilder(settings).for_studio(
        uow,
        new_id(),
        sources,
        prompt=case.prompt,
        cap_tokens=settings.notebooks.studio_context_tokens,
    )


def _language(options: SlidesOptions, pack: ContextPack) -> str:
    texts = ("\n".join(p.text for p in s.passages) for s in pack.sources)
    return resolve_language(options.language or detect_language(texts), "ru")


async def _ask(
    llm: NotebookLlm,
    run: Run,
    *,
    task: AiTask,
    system: str,
    messages: list[dict[str, Any]],
    schema: tuple[str, dict[str, Any]],
    max_tokens: int,
    replay: Path | None,
) -> dict[str, Any]:
    """One model call, or the saved answer of the same attempt in `--replay`."""
    attempt = len(run.answers) + 1
    if replay is not None:
        data = json.loads((replay / f"raw-{attempt}.json").read_text("utf-8"))
        run.answers.append(data)
        return cast(dict[str, Any], data)
    done = await llm.json(
        task=task,
        system=system,
        messages=messages,
        schema_name=schema[0],
        schema=schema[1],
        max_tokens=max_tokens,
    )
    run.answers.append(done.data)
    run.usage.append(
        {"input": done.usage.input, "output": done.usage.output}
        | {"cached": done.usage.cached, "cost_micro": done.usage.cost_micro}
    )
    run.model = done.model
    return done.data


async def generate(
    case: Case, settings: Settings, llm: NotebookLlm, replay: bool
) -> tuple[Run, ContextPack]:
    """Generate (or replay) one deck with one repair call, like the Studio job."""
    run = Run(case.name)
    pack = await _pack(case, settings)
    options = cast(SlidesOptions, HANDLER.parse_options(case.options))
    run.language = _language(options, pack)
    ctx = ProcessContext(pack, run.language, seed=1)
    system = studio_system_prompt(run.language)
    task = HANDLER.task_block(options, case.prompt)
    block = render_sources_block(pack)
    _write(case.name, "prompt.txt", f"{system}\n\n=== TASK ===\n{task}\n\n{block}")
    messages = [
        llm.context_message(block, AiTask.STUDIO_SLIDES),
        {"role": "user", "content": task},
    ]
    for _ in range(2):
        data = await _ask(
            llm,
            run,
            task=AiTask.STUDIO_SLIDES,
            system=system,
            messages=messages,
            schema=(HANDLER.schema_name, HANDLER.strict_schema()),
            max_tokens=llm.max_tokens(
                AiTask.STUDIO_SLIDES, HANDLER.max_tokens(options)
            ),
            replay=OUT / case.name if replay else None,
        )
        try:
            run.output = HANDLER.process(data, options, ctx)
            break
        except OutputInvalidError as exc:
            run.problems.append(list(exc.problems))
            text = json.dumps(data, ensure_ascii=False)
            messages = [
                *messages,
                {"role": "assistant", "content": text},
                {"role": "user", "content": repair_message(exc.problems, text)},
            ]
    return run, pack


async def revise(base: Run, settings: Settings, llm: NotebookLlm, replay: bool) -> Run:
    """Rewrite two slides of a generated deck (no sources, like `POST …/revise`)."""
    run = Run("revise", language=base.language)
    assert base.output is not None
    content = base.output.content
    slides = content["slides"]
    changes = [
        {"slide_id": slides[index]["id"], "instruction": text}
        for index, text in REVISE_CHANGES
        if index < len(slides)
    ]
    message = revise_user_message(slides, changes)
    options = cast(SlidesOptions, HANDLER.parse_options(CASES[REVISE_OF].options))
    data = await _ask(
        llm,
        run,
        task=AiTask.STUDIO_SLIDES_REVISE,
        system=revise_system_prompt(base.language, options.format),
        messages=[{"role": "user", "content": message}],
        schema=(SLIDES_REVISE_SCHEMA_NAME, revise_schema()),
        max_tokens=llm.max_tokens(AiTask.STUDIO_SLIDES_REVISE, 6_000),
        replay=OUT / "revise" if replay else None,
    )
    merged = merge_revised(
        slides,
        list(data.get("slides") or []),
        {c["slide_id"] for c in changes},
        slide_format=options.format,
        labels=set(base.output.refs_index),
    )
    run.output = ProcessedOutput(
        title=base.output.title,
        content={**content, "slides": merged},
        refs_index=base.output.refs_index,
    )
    _write("revise", "changes.json", json.dumps(changes, ensure_ascii=False, indent=2))
    return run


def _write(case: str, name: str, text: str) -> None:
    folder = OUT / case
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def _summary(run: Run, pack: ContextPack | None) -> dict[str, Any]:
    """Facts for the console and the page header."""
    assert run.output is not None
    slides = run.output.content["slides"]
    cited = Counter(
        label.split(":")[0] for slide in slides for label in slide.get("refs") or []
    )
    facts: dict[str, Any] = {
        "language": run.language,
        "slides": len(slides),
        "layouts": " ".join(s["layout"] for s in slides),
        "uncited content slides": uncited(slides) or "none",
        "calls": len(run.answers),
    }
    if pack is not None:
        facts["sources cited"] = ", ".join(
            f"S{s.n} {s.title}: {cited.get(f'S{s.n}', 0)} refs" for s in pack.sources
        )
    if run.problems:
        facts["repaired after"] = "; ".join(run.problems[0])[:300]
    if run.usage:
        facts["tokens in/out"] = "/".join(
            str(sum(u[k] or 0 for u in run.usage)) for k in ("input", "output")
        )
        cost = sum(u["cost_micro"] or 0 for u in run.usage)
        facts["cost USD"] = f"{cost / 1_000_000:.4f}" if cost else "n/a"
    if run.model:
        facts["model"] = run.model
    return facts


def _save(run: Run, pack: ContextPack | None, record: bool) -> dict[str, Any]:
    facts = _summary(run, pack)
    assert run.output is not None
    for number, answer in enumerate(run.answers, start=1):
        _write(run.name, f"raw-{number}.json", json.dumps(answer, ensure_ascii=False))
    deck = {"content": run.output.content, "refs_index": run.output.refs_index}
    _write(run.name, "deck.json", json.dumps(deck, ensure_ascii=False, indent=2))
    page = deck_html(
        run.output.content,
        run.output.refs_index,
        heading=f"{run.name}: {run.output.content.get('title')}",
        meta=facts,
    )
    _write(run.name, "deck.html", page)
    if record:
        RECORDED_DIR.mkdir(parents=True, exist_ok=True)
        target = RECORDED_DIR / f"{run.name}.json"
        shutil.copyfile(OUT / run.name / f"raw-{len(run.answers)}.json", target)
    return facts


async def main(args: argparse.Namespace) -> int:
    """Run the chosen cases and print a summary per deck."""
    settings = load_settings()
    llm = _llm(settings, args.fake)
    mode = "replay" if args.replay else type(llm.gateway).__name__
    print(f"mode: {mode}; samples: {', '.join(SAMPLES)}; out: {OUT}")
    rows: list[dict[str, Any]] = []
    runs: dict[str, Run] = {}
    names = args.case or [*CASES, "revise"]
    for name in names:
        if name == "revise":
            base = (
                runs.get(REVISE_OF)
                or (await generate(CASES[REVISE_OF], settings, llm, True))[0]
            )
            run, pack = await revise(base, settings, llm, args.replay), None
        else:
            run, pack = await generate(CASES[name], settings, llm, args.replay)
            runs[name] = run
        if run.output is None:
            print(f"\n{name}: FAILED after a repair: {run.problems}")
            continue
        facts = _save(run, pack, args.record)
        print(f"\n{name}: {run.output.content.get('title')}")
        for key, value in facts.items():
            print(f"  {key}: {value}")
        summary = f"{facts['slides']} slides, {facts['language']}"
        rows.append({"href": f"{name}/deck.html", "name": name, "summary": summary})
    (OUT / "index.html").write_text(index_html(rows), encoding="utf-8")
    print(f"\nopen {OUT / 'index.html'}")
    return 0


def parse_args() -> argparse.Namespace:
    """Command line options."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--case", action="append", choices=[*CASES, "revise"], help="repeatable"
    )
    parser.add_argument("--fake", action="store_true", help="use the fake model")
    parser.add_argument(
        "--replay", action="store_true", help="reuse the saved answers, no model call"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="copy the final answers to tests/notebooks/fixtures/slides/recorded/",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parse_args())))
