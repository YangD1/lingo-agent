"""Prompt templates live here as .md files, never inlined in code (CLAUDE.md).

A prompt's version is a hash of its text (ADR 0033 §1): git is the only source, nobody
bumps a number. Which prompts a model call used is found from the call's messages
(ADR 0033 §2): callers fill placeholders and join prompts in many ways, but each
prompt's longest literal stretch between placeholders reaches the model unchanged, so
it serves as the prompt's fingerprint. The parts of the built-in skills spliced into
prompts (ADR 0055 §1) are tracked the same way, as `skill:<name>` and
`skill:<name>/<part>`.
"""

import hashlib
import re
from functools import cache
from pathlib import Path

from app.skills import get_skills

_DIR = Path(__file__).parent
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


@cache
def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def prompt_version(name: str) -> str:
    """The first 8 hex digits of the SHA-256 of the prompt's text."""
    return _version(load_prompt(name))


@cache
def prompt_names() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in _DIR.glob("*.md")))


@cache
def prompt_texts() -> tuple[tuple[str, str], ...]:
    """(name, text) of every prompt, then of every part of the built-in skills."""
    out = [(name, load_prompt(name)) for name in prompt_names()]
    for skill in get_skills().values():
        out.append((f"skill:{skill.name}", skill.body))
        out.extend((f"skill:{skill.name}/{part}", text) for part, text in skill.references.items())
    return tuple(out)


@cache
def _fingerprints() -> tuple[tuple[str, str, str], ...]:
    """(name, version, fingerprint) for every prompt and skill part."""
    out = []
    for name, text in prompt_texts():
        pieces = (piece.strip() for piece in _PLACEHOLDER.split(text))
        out.append((name, _version(text), max(pieces, key=len)))
    return tuple(out)


def prompt_versions(text: str) -> dict[str, str] | None:
    """`{name: version}` of the prompts whose fingerprint is in `text`; None if none."""
    found = {name: version for name, version, mark in _fingerprints() if mark in text}
    return found or None
