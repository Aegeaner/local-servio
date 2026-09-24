import re
import uuid
from html import escape

from markdown import Markdown
from markdown.blockprocessors import OListProcessor
from markdown.extensions.extra import ExtraExtension

# ---------------------------------------------------------------------------
# Placeholders. Fenced code blocks use a block-level raw-HTML placeholder so
# Markdown keeps them as blocks (no extra <p> wrapper); inline code uses an
# inline tag. Math and escaped dollars use plain tokens with no characters
# Markdown treats specially, so they survive conversion untouched.
# ---------------------------------------------------------------------------
_MATH_PLACEHOLDER = "MATHPLACEHOLDER{}ENDMATHPLACEHOLDER"
_ESCAPED_DOLLAR_PLACEHOLDER = "ESCAPEDDOLLARPLACEHOLDER{}ENDESCAPEDDOLLARPLACEHOLDER"
_FENCED_PLACEHOLDER = '<div data-md-code="{}"></div>'
_INLINE_PLACEHOLDER = '<code data-md-code="{}"></code>'

_FENCED_CODE_RE = re.compile(
    r"(?m)^(?P<fence>`{3,}|~{3,})[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*\n?$",
    re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1", re.DOTALL)
_ESCAPED_DOLLAR_RE = re.compile(r"\\\$")
_ESCAPED_DOLLAR_TOKEN_RE = re.compile(
    _ESCAPED_DOLLAR_PLACEHOLDER.format(r"[0-9a-f]{32}")
)

_TAB_LENGTH = 4
_LIST_ITEM_RE = re.compile(r"^(\s*([*+-]|\d+\.)\s+)")
_LIST_MARKER_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[*+-]|\d+\.)(?P<gap>\s+)(?P<body>.*)$"
)


class _OrderedListProcessor(OListProcessor):
    """Keep the number an ordered list starts at.

    Python-Markdown is "lazy" by default: every ordered list starts at 1, so a
    list resumed after an interrupted block (for example a display equation at
    column zero) restarts its numbering. ``sane_lists`` fixes this by setting
    ``LAZY_OL = False``; we only borrow that behaviour and leave the rest of
    the list parsing untouched.
    """

    LAZY_OL = False


def _make_markdown() -> Markdown:
    md = Markdown(
        extensions=[
            ExtraExtension(),
            "markdown.extensions.nl2br",
            "markdown.extensions.tables",
        ]
    )
    md.parser.blockprocessors.register(
        _OrderedListProcessor(md.parser), "olist", 40
    )
    return md


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
    """Normalise list formatting before Markdown parsing.

    - Snap nested list markers to a multiple of the tab length. Generated
      Markdown often indents nested items by only two or three spaces, which
      Python-Markdown does not treat as nesting (``INDENT_RE`` needs at least
      ``tab_length`` spaces), so the items are folded into the parent list and
      appear as extra siblings instead of sub-items.
    - Insert a blank line before list items following a non-list line. The
      nl2br extension can otherwise cause lists to be parsed as paragraphs.
    """
    lines = content.split("\n")
    fixed: list[str] = []
    for i, line in enumerate(lines):
        marker = _LIST_MARKER_RE.match(line)
        if marker and marker.group("indent"):
            depth = (len(marker.group("indent")) - 1) // _TAB_LENGTH + 1
            line = (
                " " * (depth * _TAB_LENGTH)
                + marker.group("marker")
                + marker.group("gap")
                + marker.group("body")
            )
        if i > 0 and _LIST_ITEM_RE.match(line):
            previous = lines[i - 1].strip()
            if previous and not _LIST_ITEM_RE.match(lines[i - 1]):
                fixed.append("")
        fixed.append(line)
    return "\n".join(fixed)


# ---------------------------------------------------------------------------
# Math delimiters. Only explicit delimiters count; bare ``[...]`` is left alone
# because it is far more often an array index or array literal
# (``nums[i..n - 1]``, ``[2, -1, 3]``) than a formula.
#
# ``$$`` has to open a line (nothing but indentation before it) and inline
# ``$`` is confined to a single line. Without those limits a single unbalanced
# or currency-like delimiter pairs up with a distant one and swallows every
# paragraph in between. Lookbehinds keep LaTeX ``\\[6pt]`` row spacing and
# escaped ``\$`` from being read as delimiters.
# ---------------------------------------------------------------------------
_DISPLAY_DOLLAR_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?<!\\)\$\$(?!\$)(?P<body>.*?)(?<!\\)\$\$(?!\$)",
    re.DOTALL,
)
_DISPLAY_BRACKET_RE = re.compile(r"(?<!\\)\\\[(?P<body>.*?)(?<!\\)\\\]", re.DOTALL)
_INLINE_PAREN_RE = re.compile(r"(?<!\\)\\\((?P<body>.*?)(?<!\\)\\\)", re.DOTALL)
_INLINE_DOLLAR_RE = re.compile(
    r"(?<![\\$])\$(?!\$)(?P<body>[^\n$]*[^\s$][^\n$]*)\$(?!\$)"
)

_TEXT_COMMAND_RE = re.compile(
    r"(?P<cmd>\\(?:text|textrm|textnormal|mbox))\{(?P<body>[^{}]*)\}"
)


def _protect_escaped_dollars(text: str) -> tuple[str, dict[str, str]]:
    """Hide ``\\$`` from the math passes.

    ``\\$`` is a literal dollar. If the delimiter scans see it, the escaped
    dollar closes whatever math was open and the next ``$`` reopens it, so one
    such sequence re-partitions the rest of the document.
    """
    escapes: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        key = _ESCAPED_DOLLAR_PLACEHOLDER.format(uuid.uuid4().hex)
        escapes[key] = match.group(0)
        return key

    return _ESCAPED_DOLLAR_RE.sub(replace, text), escapes


def _fix_math_content(content: str) -> str:
    """Normalise a math fragment for MathJax.

    - Collapse newlines to spaces (so nl2br never injects ``<br>`` into math).
    - Inside text-mode commands MathJax prints ``\\_`` as a literal backslash
      (math mode handles it correctly), whereas a bare ``_`` is already
      literal there. So replace ``\\_`` with ``_`` in those bodies.

    Subscripts are passed through untouched: LaTeX already binds ``_`` to a
    single token, so bracing a whole alphanumeric run turns the valid
    ``X_1X_2`` into ``X_{1X}_{2}`` and silently changes the formula.
    """
    content = content.replace("\n", " ")

    def normalize_text_command(match: re.Match) -> str:
        body = match.group("body").replace("\\_", "_")
        return f"{match.group('cmd')}{{{body}}}"

    return _TEXT_COMMAND_RE.sub(normalize_text_command, content).strip()


def _process_math(text: str) -> tuple[str, dict[str, str]]:
    """Extract math into placeholders so Markdown never touches it."""
    placeholders: dict[str, str] = {}

    def store(content: str, *, display: bool, delimiter: str = "dollar") -> str:
        # Escape HTML metacharacters so the browser parses the math as text
        # (e.g. ``<`` in ``|S(i,j)-goal|<k`` would otherwise start a tag).
        # MathJax reads the resolved text content, so it still sees ``<``/``&``.
        fixed = escape(_fix_math_content(content), quote=False)
        key = uuid.uuid4().hex

        if delimiter == "bracket":
            rendered = rf"\[ {fixed} \]"
        elif delimiter == "paren":
            rendered = rf"\( {fixed} \)"
        elif display:
            rendered = rf"$$ {fixed} $$"
        else:
            rendered = rf"$ {fixed} $"

        placeholders[_MATH_PLACEHOLDER.format(key)] = rendered
        return _MATH_PLACEHOLDER.format(key)

    def replace_display_dollar(match: re.Match) -> str:
        # Keep the indentation: display math inside a list item has to stay
        # indented, otherwise the placeholder drops out of the list.
        token = store(match.group("body"), display=True)
        return match.group("indent") + token

    text = _DISPLAY_DOLLAR_RE.sub(replace_display_dollar, text)
    text = _DISPLAY_BRACKET_RE.sub(
        lambda m: store(m.group("body"), display=True, delimiter="bracket"), text
    )
    text = _INLINE_PAREN_RE.sub(
        lambda m: store(m.group("body"), display=False, delimiter="paren"), text
    )
    text = _INLINE_DOLLAR_RE.sub(lambda m: store(m.group("body"), display=False), text)

    return text, placeholders


def _replace_placeholders(html: str, mapping: dict[str, str]) -> str:
    """Substitute placeholder tokens until the document stops changing.

    A token can end up inside another token's replacement text (a delimiter
    pair wrapping an already extracted fragment, for example). A single pass
    would then leave the inner token printed verbatim on the page.
    """
    for _ in range(len(mapping) + 1):
        replaced = html
        for key, value in mapping.items():
            replaced = replaced.replace(key, value)
        if replaced == html:
            break
        html = replaced
    return html


def _restore_math(html: str, placeholders: dict[str, str]) -> str:
    return _replace_placeholders(html, placeholders)


def _restore_inline_code(html: str, spans: dict[str, str]) -> str:
    return _replace_placeholders(
        html,
        {
            _INLINE_PLACEHOLDER.format(key): f"<code>{escape(content, quote=False)}</code>"
            for key, content in spans.items()
        },
    )


def _restore_fenced_code(html: str, blocks: dict[str, str], md: Markdown) -> str:
    rendered: dict[str, str] = {}
    for key, source in blocks.items():
        md.reset()
        rendered[_FENCED_PLACEHOLDER.format(key)] = md.convert(source)
    return _replace_placeholders(html, rendered)


def render_markdown(text: str) -> str:
    """Convert Markdown text to HTML with math protection and code isolation."""
    text, blocks = _extract_fenced_code(text)
    text, spans = _extract_inline_code(text)
    text, escapes = _protect_escaped_dollars(text)
    text = _fix_list_spacing(text)
    text, math = _process_math(text)

    md = _make_markdown()
    html = md.convert(text)

    html = _restore_math(html, math)
    html = _restore_inline_code(html, spans)
    html = _restore_fenced_code(html, blocks, md)
    return _replace_placeholders(html, escapes)
