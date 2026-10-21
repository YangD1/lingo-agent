"""Read word senses out of Simple English Wiktionary wikitext (ADR 0062).

A page has a level-2 heading per part of speech (`== Verb ==`), a `#` line per sense
and `#:` lines under it for examples. Templates are mostly labels (`{{transitive}}`,
`{{context|baseball}}`), synonyms (`{{syn|...}}`) or pointers to another word
(`{{plural of|doe}}`); senses that only point elsewhere are dropped, the rest are
turned into plain text. Pure functions: the importer does the I/O.
"""

import bz2
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

# Headings that name a part of speech, to what the card shows. Others are skipped.
POS = {
    "noun": "noun",
    "verb": "verb",
    "phrasal verb": "verb",
    "adjective": "adjective",
    "adverb": "adverb",
    "preposition": "preposition",
    "determiner": "determiner",
    "article": "determiner",
    "pronoun": "pronoun",
    "interjection": "interjection",
    "conjunction": "conjunction",
    "coordinator": "conjunction",
    "subordinator": "conjunction",
    "expression": "phrase",
    "phrase": "phrase",
    "idiom": "phrase",
    "abbreviation": "abbreviation",
    "initialism": "abbreviation",
    "acronym": "abbreviation",
    "contraction": "contraction",
    "prefix": "prefix",
    "suffix": "suffix",
    "number": "number",
    "numeral": "number",
    "proper noun": "proper noun",
}
# Templates standing for more than one label.
_LABEL_SETS = {
    "cu noun": ("countable", "uncountable"),
    "ti verb": ("transitive", "intransitive"),
    "non-count": ("uncountable",),
    "pluralonly": ("plural only",),
}
_LABEL_ARGS = {"context", "label", "lb", "lbl"}
_SYNONYMS = {"syn", "synonyms", "synonym"}
_ANTONYMS = {"ant", "antonyms", "antonym"}
# Templates whose text is one of their arguments: {{r|countr|ies}}, {{w|Unix}}.
_JOINED = {"r"}
_LAST_ARG = {"w", "l", "link", "lc", "m"}

_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")
_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
_MEDIA = re.compile(r"\[\[(?:File|Image|Category|Media):", re.IGNORECASE)
_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SPACE = re.compile(r"\s+")
_LEFTOVER = re.compile(r"[{}\\]|\[\[|\]\]")


@dataclass(frozen=True, slots=True)
class Sense:
    """One meaning of a word, in plain text."""

    pos: str
    gloss: str
    labels: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    antonyms: tuple[str, ...] = ()


@dataclass
class _Line:
    text: str = ""
    labels: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    points_elsewhere: bool = False


def _drop_media(text: str) -> str:
    """Remove [[File:...]] and the like, captions with links inside them included."""
    while match := _MEDIA.search(text):
        depth, i = 0, match.start()
        while i < len(text):
            if text.startswith("[[", i):
                depth, i = depth + 1, i + 2
            elif text.startswith("]]", i):
                depth, i = depth - 1, i + 2
                if depth == 0:
                    break
            else:
                i += 1
        text = text[: match.start()] + text[i:]
    return text


def _clean(raw: str) -> _Line:
    """Plain text of a sense or example line, with what its templates said."""
    line = _Line()

    def template(match: re.Match[str]) -> str:
        name, *args = (part.strip() for part in match.group(1).split("|"))
        key = name.lower()
        args = [a for a in args if a and "=" not in a]
        if key.endswith(" of") or key in {"third person", "plural"}:
            line.points_elsewhere = True
            return ""
        if key in _SYNONYMS:
            line.synonyms += args
        elif key in _ANTONYMS:
            line.antonyms += args
        elif key in _LABEL_ARGS:
            line.labels += [a for a in args if a != "en"]
        elif key in _LABEL_SETS:
            line.labels += _LABEL_SETS[key]
        elif key in _JOINED:
            return "".join(args)
        elif key in _LAST_ARG:
            return args[-1] if args else ""
        elif not args and not match.group(1).strip().startswith(("-", "!")):
            line.labels.append(name)
        return ""

    text = _COMMENT.sub("", _REF.sub("", raw))
    while _TEMPLATE.search(text):
        text = _TEMPLATE.sub(template, text)
    text = _drop_media(text)
    text = _LINK.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), text)
    text = _TAG.sub("", text).replace("'''", "").replace("''", "")
    text = _SPACE.sub(" ", text).strip(" :;,")
    # What joined two labels: "{{uncountable}} or {{singular}} Relief is ..."
    if line.labels:
        text = re.sub(r"^(?:(?:or|and|,)\s+)+", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"“”':
        text = text[1:-1].strip()
    # Broken markup or a formula: nothing a card can show.
    line.text = "" if _LEFTOVER.search(text) else text
    return line


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i for i in items if i))


def parse_page(title: str, wikitext: str) -> list[Sense]:
    """The senses on a page, in page order. Proper-noun sections are kept only for a
    capitalised title ("English"), so "china" doesn't get the country."""
    senses: list[Sense] = []
    pos: str | None = None
    current: tuple[_Line, list[str]] | None = None

    def close() -> None:
        nonlocal current
        if current and pos:
            line, examples = current
            if line.text and not line.points_elsewhere:
                senses.append(
                    Sense(
                        pos=pos,
                        gloss=line.text,
                        labels=_unique(line.labels),
                        examples=_unique(examples),
                        synonyms=_unique(line.synonyms),
                        antonyms=_unique(line.antonyms),
                    )
                )
        current = None

    for raw in wikitext.splitlines():
        heading = _HEADING.match(raw)
        if heading:
            if len(heading.group(1)) == 2:
                close()
                name = re.sub(r"\s*\d+$", "", heading.group(2)).strip().lower()
                pos = POS.get(name)
                if pos == "proper noun" and title[:1].islower():
                    pos = None
            continue
        if pos is None:
            continue
        if raw.startswith("#:") and not raw.startswith("#::"):
            if current:
                example = _clean(raw[2:]).text
                if example:
                    current[1].append(example)
        elif raw.startswith("#") and not raw.startswith(("##", "#*", "#:")):
            close()
            current = (_clean(raw[1:]), [])
    close()
    return senses


def read_pages(source: Path | IO[bytes]) -> Iterator[tuple[str, str]]:
    """(title, wikitext) of each article in a pages-articles dump, bzip2 or not."""
    stream: IO[bytes]
    if isinstance(source, Path):
        stream = bz2.open(source) if source.suffix == ".bz2" else source.open("rb")
    else:
        stream = source
    with stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if not element.tag.endswith("}page"):
                continue
            ns = element.find("{*}ns")
            title = element.find("{*}title")
            text = element.find("{*}revision/{*}text")
            if ns is not None and ns.text == "0" and title is not None and title.text:
                yield title.text, (text.text or "") if text is not None else ""
            element.clear()
