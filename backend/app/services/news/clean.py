"""Feed HTML -> plain paragraphs (Q41c).

An article is stored as paragraphs separated by blank lines, with no markup: headings
and list items become paragraphs of their own; images, captions, embeds, navigation and
blocks that are nothing but links (menus, "related stories") are dropped. Some feeds put
a whole web page in the entry (NASA does), so this is about keeping the prose, not about
rendering the page faithfully.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Dropped with everything inside them.
_SKIP_TAGS = frozenset(
    {
        "script", "style", "noscript", "template", "iframe", "object", "embed", "svg",
        "math", "canvas", "video", "audio", "picture", "figure", "figcaption", "nav",
        "aside", "header", "footer", "form", "button", "select", "textarea", "head",
    }
)  # fmt: skip
# Words in a class name that mark page furniture rather than the article.
_SKIP_CLASS_WORDS = (
    "caption", "credit", "breadcrumb", "pagination", "navigation", "carousel", "share",
    "related", "originally-published", "screen-reader", "sr-only",
)  # fmt: skip
# Each of these starts a new paragraph.
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "main", "blockquote", "pre", "ul", "ol", "dl",
        "li", "dt", "dd", "table", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "br", "address", "details", "summary",
    }
)  # fmt: skip
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
     "track", "wbr"}
)  # fmt: skip
# A block whose text is at least this share links is a menu or a list of other stories.
_MAX_LINK_SHARE = 0.8
_SPACE = re.compile(r"\s+")


@dataclass
class _Block:
    text: list[str] = field(default_factory=list)
    linked: int = 0


class _Extractor(HTMLParser):
    def __init__(self, skip_class_words: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_class_words = _SKIP_CLASS_WORDS + skip_class_words
        self.paragraphs: list[str] = []
        self._stack: list[str] = []
        self._skip_depth = 0  # how many open elements are being dropped
        self._link_depth = 0
        self._block = _Block()

    def _flush(self) -> None:
        text = _SPACE.sub(" ", "".join(self._block.text)).strip()
        if text and self._block.linked / len(text) < _MAX_LINK_SHARE:
            self.paragraphs.append(text)
        self._block = _Block()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _VOID_TAGS:
            return
        classes = (dict(attrs).get("class") or "").lower()
        skip = self._skip_depth > 0 or tag in _SKIP_TAGS
        skip = skip or any(word in classes for word in self._skip_class_words)
        self._stack.append(tag)
        if skip:
            self._skip_depth += 1
        elif tag == "a":
            self._link_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._stack:
            return  # stray end tag
        # Close everything opened since `tag` (unclosed <p>, <li>...).
        while self._stack:
            open_tag = self._stack.pop()
            if self._skip_depth > 0:
                self._skip_depth -= 1
            elif open_tag == "a":
                self._link_depth -= 1
            if open_tag == tag:
                break
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._block.text.append(data)
        if self._link_depth:
            self._block.linked += len(_SPACE.sub(" ", data).strip())

    def close(self) -> None:
        super().close()
        self._flush()


def html_to_text(html: str, *, skip_class_words: tuple[str, ...] = ()) -> str:
    """Paragraphs separated by blank lines; empty when nothing readable is left.

    `skip_class_words`: a source's own page furniture, on top of the common ones.
    """
    extractor = _Extractor(skip_class_words)
    extractor.feed(html)
    extractor.close()
    paragraphs: list[str] = []
    for paragraph in extractor.paragraphs:
        if not paragraphs or paragraphs[-1] != paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def one_line(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def count_words(text: str) -> int:
    return len(text.split())
