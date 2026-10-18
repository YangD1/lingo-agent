"""`load_skill`: the tutor reads a built-in skill in a conversation (ADR 0055 §6).

Read-only and identity-free (ADR 0013 §1): the only arguments are a skill's name and
optionally one of its parts, looked up among the built-in skills. Each (skill, part) is
read at most once a turn; the graph counts these calls apart from the card tools and
keeps their results for the turn they were read in only.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.prompts import load_prompt
from app.skills import UnknownSkillError, get_skills, load_reference, load_skill

LOAD_SKILL = "load_skill"
SKILLS_SECTION = "tutor_skills"

# (skill, part): part None is SKILL.md itself.
type SkillKey = tuple[str, str | None]


class LoadSkill(BaseModel):
    """Read one of your built-in skills (the Skills section lists them) when its
    description says you need it. Its text is for you, not for the learner, and stays
    only for this turn. No card is shown."""

    model_config = ConfigDict(title=LOAD_SKILL, extra="forbid")

    name: str = Field(
        max_length=64, description="The skill's name, as the Skills section gives it."
    )
    part: str | None = Field(
        default=None,
        max_length=64,
        description="One of the parts the skill lists, for its details; leave it out to "
        "read the skill itself first.",
    )


@dataclass(frozen=True)
class SkillOutcome:
    """One `load_skill` call: what goes back to the model, and the part read (None when
    the call named no such skill or part, or repeated a read of this turn)."""

    content: str
    ok: bool
    read: SkillKey | None = None


def skill_key(args: Mapping[str, Any]) -> SkillKey | None:
    """The (skill, part) a call asks for, None when its arguments are malformed."""
    try:
        parsed = LoadSkill.model_validate(args)
    except ValidationError:
        return None
    return parsed.name, parsed.part or None


def read_skill(args: Mapping[str, Any], already: Collection[SkillKey]) -> SkillOutcome:
    """Run one call; `already` holds what this turn has read before it."""
    key = skill_key(args)
    if key is None:
        return SkillOutcome("Error: give `name` and optionally `part`, nothing else.", ok=False)
    name, part = key
    label = f"{name} ({part})" if part else name
    if key in already:
        return SkillOutcome(f"You already read {label} this turn; use it from above.", ok=True)
    try:
        if part is None:
            skill = load_skill(name)
            text = skill.body
        else:
            text = load_reference(name, part)
    except UnknownSkillError:
        if name in get_skills():
            parts = ", ".join(get_skills()[name].references) or "none"
            return SkillOutcome(f"Error: {name} has no part {part!r}; parts: {parts}.", ok=False)
        names = ", ".join(get_skills()) or "none"
        return SkillOutcome(f"Error: no skill named {name!r}; skills: {names}.", ok=False)
    opening = f'<skill name="{name}"' + (f' part="{part}">' if part else ">")
    content = f"{opening}\n{text}\n</skill>"
    if part is None and skill.references:
        content += (
            f"\n\nParts with details, read one with load_skill(name={name!r}, part=...) "
            f"only if you need it: {', '.join(skill.references)}."
        )
    return SkillOutcome(content, ok=True, read=key)


def read_earlier(key: SkillKey) -> str:
    """What stands in a later turn's history for a skill read in an earlier turn."""
    name, part = key
    label = f"{name} ({part})" if part else name
    return f"Read {label} in an earlier turn; not kept here. Read it again if you need it."


def skills_section() -> str:
    """The Skills section of the tutor's system prompt: each skill's name and when to read
    it. Fixed text, so it sits in the stable start of the prompt (ADR 0053 §1)."""
    skills = get_skills()
    if not skills:
        return ""
    listed = "\n".join(f"- {s.name}: {s.description}" for s in skills.values())
    return load_prompt(SKILLS_SECTION).replace("{skills}", listed)
