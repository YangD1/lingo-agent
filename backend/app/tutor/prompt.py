"""The tutor's name in its prompts (ADR 0032 §1)."""

from app.prompts import load_prompt


def tutor_name(name: str | None) -> list[str]:
    """The name section, or nothing for the default tutor."""
    return [load_prompt("tutor_name").replace("{name}", name).strip()] if name else []
