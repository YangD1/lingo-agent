"""HTML in a text for reading, as Markdown (task 85, the backend's fallback).

The input box already turns pasted HTML into Markdown (frontend `lib/paste.ts`); this catches
what gets past it: a text opened by the tutor, an older client, the API called directly.
Tags outside code become Markdown marks, dangerous elements (scripts, frames, forms…) go
whole, and text outside any tag is kept exactly as written, since it is the learner's own
Markdown. Raw HTML is never rendered either way: this keeps the structure, not the page safe.
Standard library only (`html.parser`), so no new dependency on a small server.
"""

import re
from html.parser import HTMLParser

_KNOWN = {
    *"html head body div span p br hr ul ol li dl dt dd table thead tbody tfoot tr td th".split(),
    *"caption blockquote pre code b strong i em u s del ins strike sub sup small mark a".split(),
    *"section article header footer main aside nav figure figcaption details summary".split(),
    *"font center script style iframe img meta link form input button svg noscript".split(),
    *"h1 h2 h3 h4 h5 h6 title template object embed textarea select option".split(),
    *"frame frameset applet picture canvas video audio source track map base label".split(),
}
# A tag of a known element, so `Array<string>` or `a < b > c` don't count.
_TAG = re.compile(rf"</?(?:{'|'.join(sorted(_KNOWN))})\b[^<>]*>", re.IGNORECASE)

# Dropped with everything inside them. (Void ones, like img, have nothing inside.)
_DROPPED = set(
    "script style noscript template iframe frame frameset object embed applet img picture svg "
    "canvas video audio source track map nav form input button select option textarea head "
    "title meta link base".split()
)
_VOID = set("area base br col embed hr img input link meta source track wbr".split())
# Paragraph-like: a blank line before and after (but not inside a list item).
_BLOCK = set(
    "p div section article header footer main aside figure figcaption details summary dl dt dd "
    "center".split()
)
_EMPHASIS = {"b": "**", "strong": "**", "i": "*", "em": "*", "s": "~~", "del": "~~", "strike": "~~"}

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?!`)[\s\S]*?[^`]\1(?!`)")
_LINK = re.compile(r"^(?:https?:|mailto:)", re.IGNORECASE)


def from_html(text: str) -> str:
    """The text with its HTML as Markdown; a text without HTML tags comes back unchanged."""
    if not _TAG.search(text):
        return text
    out: list[str] = []
    prose: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if prose:
            out.append(_prose(prose))
        prose.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        mark = _FENCE.match(line)
        if fence:
            out.append(line)
            if mark and line.strip() == mark.group(1) and mark.group(1).startswith(fence):
                fence = None
        elif mark:
            flush()
            fence = mark.group(1)
            out.append(line)
        else:
            prose.append(line)
    flush()
    return "\n".join(out).strip("\n")


def _prose(lines: list[str]) -> str:
    """Lines outside fenced code: inline code is held aside so `<b>` written as code stays."""
    text = "\n".join(lines)
    if not _TAG.search(text):
        return text
    spans: list[str] = []

    def hold(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"{len(spans) - 1}"

    converter = _ToMarkdown()
    converter.feed(_INLINE_CODE.sub(hold, text))
    converter.close()
    return re.sub(r"(\d+)", lambda m: spans[int(m.group(1))], converter.markdown())


class _ToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        # Where a link, quote, cell or table being collected starts in `parts`.
        self.marks: list[tuple[str, int, str]] = []
        self.skipping: list[str] = []  # open dropped elements
        self.depth = 0  # open HTML elements: text inside them collapses its whitespace
        self.pre = 0
        self.fresh = True  # at the start of a line: leading whitespace goes
        self.lists: list[dict[str, int]] = []  # {"ordered": 0/1, "n": items so far, "width": …}
        self.tables: list[list[list[str]]] = []

    # Output ------------------------------------------------------------------------------

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text)

    def _floor(self) -> int:
        return self.marks[-1][1] if self.marks else 0

    def _break(self, newlines: int) -> None:
        """End the line (1) or the paragraph (2), unless nothing has been written yet. A
        paragraph already ended stays ended."""
        floor = self._floor()
        trailing = ""
        while len(self.parts) > floor and not self.parts[-1].strip(" \t\n"):
            trailing = self.parts.pop() + trailing
        if len(self.parts) > floor:
            last = self.parts[-1]
            self.parts[-1] = last.rstrip(" \t\n")
            trailing = last[len(self.parts[-1]) :] + trailing
            self.parts.append("\n" * max(newlines, min(trailing.count("\n"), 2)))
        self.fresh = True

    def _emit(self, text: str) -> None:
        self.parts.append(text)
        self.fresh = False

    def _collect(self, kind: str, extra: str = "") -> None:
        self.marks.append((kind, len(self.parts), extra))

    def _collected(self, kind: str) -> tuple[str, str] | None:
        """What was written since `_collect(kind)`, taken out of the output."""
        if not self.marks or self.marks[-1][0] != kind:
            return None
        _, start, extra = self.marks.pop()
        content = "".join(self.parts[start:])
        del self.parts[start:]
        return content, extra

    # Parser events -----------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping:
            if tag == self.skipping[-1]:
                self.skipping.append(tag)
            return
        if tag in _DROPPED:
            if tag not in _VOID:
                self.skipping.append(tag)
            return
        if tag not in _KNOWN:
            self._emit(self.get_starttag_text() or "")  # not HTML we know: keep it as text
            return
        if tag not in _VOID:
            self.depth += 1
        if self.pre:
            return
        if tag in _BLOCK:
            if not self.lists:
                self._break(2)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._break(2)
            self._emit("#" * int(tag[1]) + " ")
            self.fresh = True
        elif tag == "br":
            self._break(1)
        elif tag == "hr":
            self._break(2)
            self._emit("---")
            self._break(2)
        elif tag in _EMPHASIS:
            self._emit(_EMPHASIS[tag])
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._break(2)
            self._emit("```\n")
            self.pre += 1
        elif tag == "a":
            self._collect("a", dict(attrs).get("href") or "")
        elif tag == "blockquote":
            self._break(2)
            self._collect("blockquote")
        elif tag in {"ul", "ol"}:
            self._break(1 if self.lists else 2)
            self.lists.append({"ordered": int(tag == "ol"), "n": 0, "width": 0})
        elif tag == "li":
            self._break(1)
            if not self.lists:
                self.lists.append({"ordered": 0, "n": 0, "width": 0})
            current = self.lists[-1]
            current["n"] += 1
            prefix = f"{current['n']}. " if current["ordered"] else "- "
            current["width"] = len(prefix)
            self._emit(" " * sum(outer["width"] for outer in self.lists[:-1]) + prefix)
            self.fresh = True
        elif tag == "table":
            self._break(2)
            self.tables.append([])
            self._collect("table")
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in {"td", "th"} and self.tables:
            self._collect("cell")
            self.fresh = True

    def handle_endtag(self, tag: str) -> None:
        if self.skipping:
            if tag == self.skipping[-1]:
                self.skipping.pop()
            return
        if tag in _DROPPED or tag in _VOID:
            return
        if tag not in _KNOWN:
            self._emit(f"</{tag}>")
            return
        self.depth = max(self.depth - 1, 0)
        if self.pre and tag != "pre":
            return
        if tag in _BLOCK:
            if not self.lists:
                self._break(2)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._break(2)
        elif tag in _EMPHASIS:
            self._emit(_EMPHASIS[tag])
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self.pre = max(self.pre - 1, 0)
            self._break(1)
            self._emit("```")
            self._break(2)
        elif tag == "a" and (link := self._collected("a")):
            content, href = link
            href = href.strip()
            if content.strip() and _LINK.match(href):
                href = re.sub(r"[\s()]", lambda m: f"%{ord(m.group(0)):02X}", href)
                self._emit(f"[{content.strip()}]({href})")
            else:
                self._emit(content)
        elif tag == "blockquote" and (quote := self._collected("blockquote")):
            lines = re.sub(r"\n{3,}", "\n\n", quote[0].strip()).split("\n")
            self._emit("\n".join(f"> {line}" if line.strip() else ">" for line in lines))
            self._break(2)
        elif tag in {"ul", "ol"} and self.lists:
            self.lists.pop()
            self._break(1 if self.lists else 2)
        elif tag in {"td", "th"} and self.tables and (cell := self._collected("cell")):
            if not self.tables[-1]:
                self.tables[-1].append([])
            self.tables[-1][-1].append(" ".join(cell[0].split()).replace("|", "\\|"))
        elif tag == "table" and self.tables:
            rows = [row for row in self.tables.pop() if row]
            self._collected("table")
            self._table(rows)

    def handle_data(self, data: str) -> None:
        if self.skipping:
            return
        if self.pre:
            self._emit(data)
            return
        if self.depth:
            data = re.sub(r"\s+", " ", data)
        if self.fresh:
            data = data.lstrip(" \t") if not self.depth else data.lstrip()
        if data:
            self.parts.append(data)
            self.fresh = data.endswith("\n")

    def _table(self, rows: list[list[str]]) -> None:
        """The first row is the header: a pasted table rarely marks one."""
        if not rows:
            return
        width = max(len(row) for row in rows)
        lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
        lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
        self._break(2)
        self._emit("\n".join(lines))
        self._break(2)
