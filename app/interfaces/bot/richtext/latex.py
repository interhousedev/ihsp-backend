"""Converts the common LaTeX subset to readable Unicode for Telegram text."""

import re
from dataclasses import dataclass

_SUPERSCRIPT = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽",
    ")": "⁾", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ",
    "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ",
    "n": "ⁿ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
    "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
}  # fmt: skip

_SUBSCRIPT = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍",
    ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ",
    "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}  # fmt: skip

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ",
    "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}  # fmt: skip

_SYMBOLS = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "le": "≤",
    "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈",
    "equiv": "≡", "sim": "∼", "infty": "∞", "to": "→", "rightarrow": "→",
    "leftarrow": "←", "gets": "←", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔", "iff": "⇔", "implies": "⇒",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "varnothing": "∅", "forall": "∀",
    "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨", "sum": "∑", "prod": "∏",
    "int": "∫", "oint": "∮", "partial": "∂", "nabla": "∇", "degree": "°",
    "circ": "∘", "ldots": "…", "dots": "…", "cdots": "…", "mid": "|",
    "perp": "⊥", "parallel": "∥", "angle": "∠", "prime": "′", "star": "⋆",
    "bullet": "•", "hbar": "ħ", "ell": "ℓ", "aleph": "ℵ", "quad": " ",
    "qquad": "  ", "lbrace": "{", "rbrace": "}", "langle": "⟨", "rangle": "⟩",
    "ast": "∗", "oplus": "⊕", "otimes": "⊗", "mapsto": "↦", "lvert": "|",
    "rvert": "|", "vert": "|", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈",
    "rceil": "⌉", "backslash": "\\",
}  # fmt: skip

_OPERATORS = frozenset(
    {
        "log", "ln", "lg", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin",
        "arccos", "arctan", "sinh", "cosh", "tanh", "exp", "lim", "min", "max",
        "sup", "inf", "det", "gcd", "arg", "dim", "ker", "deg", "mod",
    }
)  # fmt: skip

_TEXT_COMMANDS = frozenset(
    {"text", "textrm", "textbf", "textit", "mathrm", "mathbf", "mathit",
     "mathsf", "mathtt", "operatorname"}
)  # fmt: skip

_IGNORED = frozenset(
    {"left", "right", "displaystyle", "textstyle", "scriptstyle", "limits",
     "nolimits", "big", "Big", "bigg", "Bigg"}
)  # fmt: skip

# Constructs Unicode text cannot show well; display formulas with them need images.
_IMAGE_COMMANDS = frozenset(
    {"sum", "prod", "int", "oint", "lim", "binom", "overline", "underline",
     "overbrace", "underbrace", "bigcup", "bigcap"}
)  # fmt: skip

_FRACTIONS = frozenset({"frac", "dfrac", "tfrac"})
_SIMPLE_OPERAND = re.compile(r"\w{1,3}")


@dataclass(frozen=True, slots=True)
class LatexResult:
    """Unicode text for a LaTeX fragment and whether it needs an image to read well."""

    text: str
    needs_image: bool


def latex_to_unicode(source: str) -> LatexResult:
    """Convert a LaTeX fragment to readable Unicode text.

    Args:
        source: LaTeX without its math delimiters.

    Returns:
        The Unicode text and a flag set for constructs Unicode cannot express well.
    """
    converter = _Converter()
    text = converter.convert(source)
    return LatexResult(
        text=re.sub(r" {2,}", " ", text).strip(), needs_image=converter.needs_image
    )


class _Converter:
    """Single-use LaTeX walker that records whether the fragment needs an image."""

    def __init__(self) -> None:
        self.needs_image = False
        self._frac_depth = 0

    def convert(self, src: str) -> str:
        """Convert a LaTeX fragment, left to right."""
        out: list[str] = []
        i = 0
        while i < len(src):
            ch = src[i]
            if ch == "\\":
                i, piece = self._command(src, i)
            elif ch in "^_":
                i, piece = self._script(src, i)
            elif ch in "{}":
                i, piece = i + 1, ""
            elif ch == "~":
                i, piece = i + 1, " "
            else:
                i, piece = i + 1, ch
            out.append(piece)
        return "".join(out)

    def _command(self, src: str, i: int) -> tuple[int, str]:
        """Convert the backslash sequence starting at ``i``."""
        j = i + 1
        if j >= len(src):
            return j, "\\"
        if src[j].isalpha():
            k = j
            while k < len(src) and src[k].isalpha():
                k += 1
            return self._named(src, src[j:k], k)
        ch = src[j]
        if ch == "\\":
            return j + 1, " "
        if ch == "!":
            return j + 1, ""
        if ch in ",;: ":
            return j + 1, " "
        return j + 1, ch

    def _named(self, src: str, name: str, k: int) -> tuple[int, str]:
        """Convert a named command whose name ends before ``k``."""
        if name in _FRACTIONS:
            return self._fraction(src, k)
        if name == "sqrt":
            return self._sqrt(src, k)
        if name in _TEXT_COMMANDS:
            raw, j = _read_arg(src, k)
            return j, self.convert(raw)
        if name in ("begin", "end"):
            return self._environment(src, name, k)
        if name in _IGNORED:
            return k, ""
        if name in _IMAGE_COMMANDS:
            self.needs_image = True
        return k, self._symbol(name)

    def _environment(self, src: str, name: str, k: int) -> tuple[int, str]:
        r"""Skip the `{name}` argument of \\begin or \\end; environments need images."""
        _, j = _read_arg(src, k)
        self.needs_image = self.needs_image or name == "begin"
        return j, ""

    def _symbol(self, name: str) -> str:
        """Return the Unicode text of a command name, flagging unknown commands."""
        if name in _GREEK:
            return _GREEK[name]
        if name in _SYMBOLS:
            return _SYMBOLS[name]
        if name not in _OPERATORS:
            self.needs_image = True
        return name

    def _fraction(self, src: str, k: int) -> tuple[int, str]:
        r"""Convert ``\\frac{num}{den}``."""
        raw_num, j = _read_arg(src, k)
        raw_den, end = _read_arg(src, j)
        if self._frac_depth > 0:
            self.needs_image = True
        self._frac_depth += 1
        num = self.convert(raw_num)
        den = self.convert(raw_den)
        self._frac_depth -= 1
        return end, _join_fraction(num, den)

    def _sqrt(self, src: str, k: int) -> tuple[int, str]:
        r"""Convert ``\\sqrt[index]{body}``."""
        prefix = ""
        if k < len(src) and src[k] == "[":
            end = src.find("]", k)
            if end != -1:
                prefix = _map_script(self.convert(src[k + 1 : end]), _SUPERSCRIPT) or ""
                k = end + 1
        raw, j = _read_arg(src, k)
        body = self.convert(raw)
        if not _SIMPLE_OPERAND.fullmatch(body):
            body = f"({body})"
        return j, f"{prefix}√{body}"

    def _script(self, src: str, i: int) -> tuple[int, str]:
        """Convert a superscript or subscript whose ``^`` or ``_`` sits at ``i``."""
        op = src[i]
        raw, j = _read_arg(src, i + 1)
        text = self.convert(raw)
        table = _SUPERSCRIPT if op == "^" else _SUBSCRIPT
        mapped = _map_script(text, table)
        if mapped is not None:
            return j, mapped
        if not text:
            return j, ""
        if len(text) == 1:
            return j, f"{op}{text}"
        return j, f"{op}({text})"


def _map_script(text: str, table: dict[str, str]) -> str | None:
    """Map every character through a script table, or return None if one is missing."""
    mapped = [table.get(ch) for ch in text]
    if any(part is None for part in mapped):
        return None
    return "".join(part for part in mapped if part is not None)


def _join_fraction(num: str, den: str) -> str:
    """Join numerator and denominator with a fraction slash when both are short."""
    if _SIMPLE_OPERAND.fullmatch(num) and _SIMPLE_OPERAND.fullmatch(den):
        return f"{num}⁄{den}"
    num_part = num if _SIMPLE_OPERAND.fullmatch(num) else f"({num})"
    den_part = den if _SIMPLE_OPERAND.fullmatch(den) else f"({den})"
    return f"{num_part}/{den_part}"


def _read_arg(src: str, pos: int) -> tuple[str, int]:
    """Read one LaTeX argument (a balanced group, a command, or one character)."""
    while pos < len(src) and src[pos] == " ":
        pos += 1
    if pos >= len(src):
        return "", pos
    if src[pos] == "{":
        return _balanced_group(src, pos)
    if src[pos] == "\\":
        end = pos + 1
        while end < len(src) and src[end].isalpha():
            end += 1
        if end == pos + 1 and end < len(src):
            end += 1
        return src[pos:end], end
    return src[pos], pos + 1


def _balanced_group(src: str, pos: int) -> tuple[str, int]:
    """Return the contents of the brace group at ``pos`` and the index after it."""
    depth = 0
    i = pos
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[pos + 1 : i], i + 1
        i += 1
    return src[pos + 1 :], len(src)
