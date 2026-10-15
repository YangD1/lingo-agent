"""Markdown in a reading document (task 84): blocks that keep their structure, and the
plain words behind the marks.

A pasted text is often Markdown. Its blocks are what the reading view shows, translates
and analyses one by one, so a list or a table must stay one block with its line breaks,
a heading stands alone, and a fenced code block is kept exactly (Q84c: not translated).
"""

import re

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
# Lines whose breaks carry meaning: list items, quotes, table rows. (Not indentation
# alone: a pasted paragraph indented four spaces would read as code.)
_STRUCTURED = re.compile(r"^(\s{0,3}([-*+]|\d{1,9}[.)])\s|\s{0,3}>|\s*\|)")


def is_code(block: str) -> bool:
    """A fenced code block: shown as it is, never translated or analysed."""
    return bool(_FENCE.match(block))


def blocks_of(text: str) -> list[str]:
    """Blocks separated by blank lines. Prose lines join into one line; a block with list
    items, quotes or table rows keeps its lines; a heading is a block of its own; a fenced
    code block runs to its closing fence, blank lines and all."""
    blocks: list[list[str]] = []
    current: list[str] = []
    fence: str | None = None

    def close() -> None:
        nonlocal current
        if current:
            blocks.append(current)
        current = []

    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.rstrip()
        if fence:
            current.append(line)
            if line.strip().startswith(fence):
                fence = None
                close()
            continue
        opened = _FENCE.match(line)
        if opened:
            close()
            fence = opened.group(1)[0] * 3
            current.append(line)
        elif not line.strip():
            close()
        elif _HEADING.match(line):
            close()
            blocks.append([line.strip()])
        else:
            current.append(line)
    close()
    return [_joined(lines) for lines in blocks]


def _joined(lines: list[str]) -> str:
    if is_code(lines[0]):
        return "\n".join(lines)
    if any(_STRUCTURED.match(line) for line in lines):
        return "\n".join(lines).strip("\n")
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


_INLINE = [
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # images: their alt text
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # links: their text
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"\1"),
    (re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
]
_LINE_MARKS = re.compile(r"^\s*(#{1,6}\s+|>\s?|[-*+]\s+|\d{1,9}[.)]\s+)+")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def plain(block: str) -> str:
    """The block's words without the Markdown marks, on one line."""
    if is_code(block):
        return ""
    lines = []
    for line in block.split("\n"):
        if _TABLE_RULE.match(line):
            continue
        line = _LINE_MARKS.sub("", line).strip().strip("|").replace("|", " ")
        for pattern, keep in _INLINE:
            line = pattern.sub(keep, line)
        lines.append(line)
    return " ".join(" ".join(lines).split())


def contains(block: str, sentence: str) -> bool:
    """Whether the sentence's words run, in order, in the block, whatever marks either side
    kept."""

    def words(text: str) -> str:
        return " ".join(re.findall(r"[\w'\u2019-]+", text.lower()))

    return f" {words(sentence)} " in f" {words(plain(block))} "
