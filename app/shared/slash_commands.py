"""Slash commands of the AI chats: `/cards photosynthesis` and friends.

The clients send `{command, args}` (or plain text that starts with `/command`);
this module is the one place that knows what each command means. A chat stores
the short form (`/cards photosynthesis`); the model receives the expanded prompt,
so the stored history stays readable and a change here changes old chats too.
"""

import re
from dataclasses import dataclass

from app.shared.base_error import ValidationFailedError


class UnknownCommandError(ValidationFailedError):
    """The slash command is not one the assistant knows (params: command, known)."""

    code = "ai/unknown-command"
    message_key = "ai-unknown-command"


@dataclass(frozen=True)
class SlashCommand:
    """One command: its name, what the model is told to do and the tool it may use."""

    name: str
    instruction: str
    tool: str | None = None
    needs_args: bool = True


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand(
        "goal",
        "The user sets the goal of this chat. Restate it in one sentence, suggest "
        "two or three first steps, and keep it in mind for every later answer. "
        "Goal: {args}",
    ),
    SlashCommand(
        "cards",
        "Make flash cards (question and answer, one fact per card, 8 to 15 cards) "
        "on this topic or from the attached files. When the create_flashcard_set "
        "tool is available, propose the set with it. Topic: {args}",
        tool="create_flashcard_set",
    ),
    SlashCommand(
        "quiz",
        "Make a short quiz of 5 to 8 questions on this topic or the attached "
        "files. Mix question types, give the answer key and a one-line "
        "explanation for each answer after the questions. Topic: {args}",
    ),
    SlashCommand(
        "summary",
        "Write structured study notes (a conspect): a title, headings, short "
        "bullet points, key terms in bold and a three-line recap. Topic: {args}",
    ),
    SlashCommand(
        "mindmap",
        "Draw a mind map as a nested Markdown list: the topic in the root, "
        "three to six branches, short leaves. Topic: {args}",
    ),
    SlashCommand(
        "slides",
        "Plan a slide deck: for every slide give a title, two to four bullets "
        "and a speaker note; start with a title slide and end with a summary. "
        "Topic: {args}",
    ),
    SlashCommand(
        "report",
        "Write a short report: introduction, main sections with headings, "
        "conclusion. Keep it factual and say what you are unsure about. "
        "Topic: {args}",
    ),
    SlashCommand(
        "table",
        "Answer with a Markdown table that compares or lists the key facts, "
        "with a clear header row and one sentence under it. Subject: {args}",
    ),
    SlashCommand(
        "explain",
        "Explain this simply, step by step, with one everyday example, and end "
        "with one question that checks understanding. Subject: {args}",
    ),
    SlashCommand(
        "translate",
        "Translate the text below. If the user names a target language at the "
        "start, use it; otherwise translate into the language of the chat. "
        "Keep the formatting. Text: {args}",
    ),
    SlashCommand(
        "help",
        "List these commands with one line each, then ask what the user wants "
        "to do: {commands}. Extra words from the user: {args}",
        needs_args=False,
    ),
)

BY_NAME: dict[str, SlashCommand] = {c.name: c for c in COMMANDS}
NAMES: tuple[str, ...] = tuple(BY_NAME)

_TYPED = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)
_NO_ARGS = (
    "(nothing yet: ask the user, in one short sentence, for the topic, or use "
    "the attached files if there are any)"
)


@dataclass(frozen=True)
class ParsedCommand:
    """A command and its arguments, before it is checked against the registry."""

    command: str
    args: str


def parse_typed(text: str) -> ParsedCommand | None:
    """Return the command of a message that starts with `/name`, else `None`.

    `/usr/bin` or `/ 5` are not commands, so ordinary text with a slash is left alone.
    """
    match = _TYPED.match(text.strip())
    if match is None:
        return None
    return ParsedCommand(match.group(1).lower(), (match.group(2) or "").strip())


def resolve(command: str, args: str = "") -> SlashCommand:
    """Return the command or raise `UnknownCommandError`.

    The error message lists the known commands.
    """
    found = BY_NAME.get(command.strip().lstrip("/").lower())
    if found is None:
        raise UnknownCommandError(
            params={
                "command": command.strip().lstrip("/"),
                "known": ", ".join(f"/{n}" for n in NAMES),
            }
        )
    return found


def stored_text(command: str | None, args: str, text: str) -> str:
    """Return the text a chat stores: `/cmd args` for a command, else the text.

    An explicit `command` wins over `text`; typed text that starts with `/name` is
    checked as a command too. Unknown names raise `UnknownCommandError`.
    """
    if command:
        spec = resolve(command)
        return f"/{spec.name} {args.strip()}".strip()
    parsed = parse_typed(text)
    if parsed is None:
        return text
    spec = resolve(parsed.command)
    return f"/{spec.name} {parsed.args}".strip()


def expand(text: str) -> str:
    """Return the prompt for the model.

    The stored instruction of a `/cmd args`, else `text` itself.
    """
    parsed = parse_typed(text)
    if parsed is None or parsed.command not in BY_NAME:
        return text
    spec = BY_NAME[parsed.command]
    args = parsed.args or (_NO_ARGS if spec.needs_args else "")
    commands = ", ".join(f"/{n}" for n in NAMES)
    return spec.instruction.format(args=args, commands=commands)
