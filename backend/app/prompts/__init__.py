"""Prompt templates live here as .md files, never inlined in code (CLAUDE.md).

A prompt's version is a hash of its text (ADR 0033 §1): git is the only source, nobody
bumps a number. Which prompts a model call used is found from the call's messages
(ADR 0033 §2): callers fill placeholders and join prompts in many ways, but each
prompt's longest literal stretch between placeholders reaches the model unchanged, so
it serves as the prompt's fingerprint.
"""

import hashlib
import re
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


@cache
def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def prompt_version(name: str) -> str:
    """The first 8 hex digits of the SHA-256 of the prompt's text."""
    return hashlib.sha256(load_prompt(name).encode()).hexdigest()[:8]


@cache
def prompt_names() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in _DIR.glob("*.md")))


@cache
def _fingerprints() -> tuple[tuple[str, str, str], ...]:
    """(name, version, fingerprint) for every prompt."""
    out = []
    for name in prompt_names():
        pieces = (piece.strip() for piece in _PLACEHOLDER.split(load_prompt(name)))
        out.append((name, prompt_version(name), max(pieces, key=len)))
    return tuple(out)


def prompt_versions(text: str) -> dict[str, str] | None:
    """`{name: version}` of the prompts whose fingerprint is in `text`; None if none."""
    found = {name: version for name, version, mark in _fingerprints() if mark in text}
    return found or None
