"""The tutor's name in its prompts (ADR 0032 §1, ADR 0040 §2)."""

from app.prompts import load_prompt
from app.tutor.service import DEFAULT_NAME


def tutor_name(name: str | None) -> list[str]:
    """The name section; the default tutor is called by the default name."""
    return [load_prompt("tutor_name").replace("{name}", name or DEFAULT_NAME).strip()]
