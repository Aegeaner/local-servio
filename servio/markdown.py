import re
import uuid
from html import escape

from markdown import Markdown
from markdown.extensions.extra import ExtraExtension

# ---------------------------------------------------------------------------
# Placeholders. Fenced code blocks use a block-level raw-HTML placeholder so
# Markdown keeps them as blocks (no extra <p> wrapper); inline code uses an
# inline tag. Math placeholders are plain tokens with no special characters.
# ---------------------------------------------------------------------------
_MATH_PLACEHOLDER = "MATHPLACEHOLDER{}ENDMATHPLACEHOLDER"
_FENCED_PLACEHOLDER = '<div data-md-code="{}"></div>'
_INLINE_PLACEHOLDER = '<code data-md-code="{}"></code>'

_FENCED_CODE_RE = re.compile(
    r"(?m)^(?P<fence>`{3,}|~{3,})[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*\n?$",
    re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1", re.DOTALL)

_LIST_ITEM_RE = re.compile(r"^(\s*([*+-]|\d+\.)\s+)")


def _make_markdown() -> Markdown:
    return Markdown(
        extensions=[
            ExtraExtension(),
            "markdown.extensions.nl2br",
            "markdown.extensions.tables",
        ]
    )


def _extract_fenced_code(text: str) -> tuple[str, dict[str, str]]:
    blocks: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        key = uuid.uuid4().hex
        blocks[key] = match.group(0)
        return f"\n{_FENCED_PLACEHOLDER.format(key)}\n"

    return _FENCED_CODE_RE.sub(replace, text), blocks


def _extract_inline_code(text: str) -> tuple[str, dict[str, str]]:
    spans: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        key = uuid.uuid4().hex
        spans[key] = match.group(2)
        return _INLINE_PLACEHOLDER.format(key)

    return _INLINE_CODE_RE.sub(replace, text), spans


def _fix_list_spacing(content: str) -> str:
    """Insert a blank line before list items following a non-list line.

    The nl2br extension can otherwise cause lists to be parsed as paragraphs.
    """
    lines = content.split("\n")
    fixed: list[str] = []
    for i, line in enumerate(lines):
        if i > 0 and _LIST_ITEM_RE.match(line):
            previous = lines[i - 1].strip()
            if previous and not _LIST_ITEM_RE.match(lines[i - 1]):
                fixed.append("")
        fixed.append(line)
    return "\n".join(fixed)


def _fix_math_content(content: str) -> str:
    """Normalise a math fragment for MathJax.

    - Collapse newlines to spaces (so nl2br never injects ``<br>`` into math).
    - Brace bare alphanumeric subscripts (``_a`` -> ``_{a}``) without touching
      escaped underscores (``\\_``).
    """
    content = content.replace("\n", " ")
    content = re.sub(r"(?<!\\)_([a-zA-Z0-9]+)", r"_{\1}", content)
    return content.strip()


def _process_math(text: str) -> tuple[str, dict[str, str]]:
    """Extract math into placeholders so Markdown never touches it.

    Explicit delimiters (``$$``, ``\\[``, ``\\(``, ``$``) are handled first;
    a bare ``[...]`` heuristic runs last as a fallback.
    """
    placeholders: dict[str, str] = {}

    def store(content: str, is_display: bool, delimiter: str = "dollar") -> str:
        fixed = _fix_math_content(content)
        key = uuid.uuid4().hex

        if delimiter == "bracket":
            rendered = rf"\[ {fixed} \]"
        elif delimiter == "paren":
            rendered = rf"\( {fixed} \)"
        elif is_display:
            rendered = rf"$$ {fixed} $$"
        else:
            rendered = rf"$ {fixed} $"

        placeholders[_MATH_PLACEHOLDER.format(key)] = rendered
        return _MATH_PLACEHOLDER.format(key)

    text = re.sub(
        r"\$\$(.*?)\$\$", lambda m: store(m.group(1), True), text, flags=re.DOTALL
    )
    text = re.sub(
        r"\\\[(.*?)\\\]",
        lambda m: store(m.group(1), True, delimiter="bracket"),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\((.*?)\\\)",
        lambda m: store(m.group(1), False, delimiter="paren"),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\$(.*?)\$", lambda m: store(m.group(1), False), text, flags=re.DOTALL
    )

    bracket_pattern = r"\[\s*(.*?)\s*\]"

    def replace_bracket_math(match: re.Match) -> str:
        content = match.group(1).strip()
        if any(
            char in content
            for char in ["\\", "^", "_", "{", "}", "=", "<", ">", "+", "-", "*", "/"]
        ):
            return store(content, True, delimiter="bracket")
        return match.group(0)

    text = re.sub(bracket_pattern, replace_bracket_math, text, flags=re.DOTALL)
    return text, placeholders


def _restore_math(html: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        html = html.replace(key, value)
    return html


def _restore_inline_code(html: str, spans: dict[str, str]) -> str:
    for key, content in spans.items():
        escaped = escape(content, quote=False)
        html = html.replace(_INLINE_PLACEHOLDER.format(key), f"<code>{escaped}</code>")
    return html


def _restore_fenced_code(html: str, blocks: dict[str, str], md: Markdown) -> str:
    for key, source in blocks.items():
        md.reset()
        html = html.replace(_FENCED_PLACEHOLDER.format(key), md.convert(source))
    return html


def render_markdown(text: str) -> str:
    """Convert Markdown text to HTML with math protection and code isolation."""
    text, blocks = _extract_fenced_code(text)
    text, spans = _extract_inline_code(text)
    text = _fix_list_spacing(text)
    text, math = _process_math(text)

    md = _make_markdown()
    html = md.convert(text)

    html = _restore_math(html, math)
    html = _restore_inline_code(html, spans)
    html = _restore_fenced_code(html, blocks, md)
    return html
