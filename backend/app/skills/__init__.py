"""Built-in skills (ADR 0055 §1): know-how the exercise pipeline splices into its prompts
and the tutor reads on demand with `load_skill`.

Each skill is a directory here in the Agent Skills layout: `SKILL.md` with a front
matter (`name`, `description`) and the general rules, and `references/<part>.md` with
details read only when needed. Skills are hand-reviewed content checked into the repo,
like the prompts, and validated at startup. Only these built-in skills load, and only by
name: a name is looked up among the skills found here, never joined into a path.
"""

import re
from functools import cache
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SKILLS_DIR = Path(__file__).parent
SKILL_FILE = "SKILL.md"
REFERENCES_DIR = "references"
# The Agent Skills naming rule: lowercase letters, digits and single hyphens.
_NAME_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_NAME = re.compile(_NAME_PATTERN)
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class SkillCatalogError(Exception):
    """A built-in skill is missing a field or badly formed."""


class UnknownSkillError(LookupError):
    """No built-in skill, or no part of one, by that name."""


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=_NAME_PATTERN, max_length=64)
    # What it is for and when to read it: listed in the tutor's system prompt.
    description: str = Field(min_length=1, max_length=1024)
    # SKILL.md after the front matter.
    body: str = Field(min_length=1)
    # references/<part>.md by part name, in name order.
    references: dict[str, str] = {}

    @model_validator(mode="after")
    def _check_parts(self) -> Self:
        for part, text in self.references.items():
            if not _NAME.match(part):
                raise ValueError(f"{self.name}: reference name {part!r} is not lowercase-hyphen")
            if not text:
                raise ValueError(f"{self.name}: reference {part} is empty")
        return self


def parse_skill(directory: Path) -> Skill:
    """The skill in `directory`. Raises SkillCatalogError when it is badly formed or its
    name is not the directory's (as in Agent Skills)."""
    path = directory / SKILL_FILE
    match = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if match is None:
        raise SkillCatalogError(f"{path}: no front matter between --- lines")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillCatalogError(f"{path}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillCatalogError(f"{path}: front matter must be a mapping")
    references = {
        ref.stem: ref.read_text(encoding="utf-8").strip()
        for ref in sorted((directory / REFERENCES_DIR).glob("*.md"))
    }
    try:
        skill = Skill.model_validate(
            {**meta, "body": match.group(2).strip(), "references": references}
        )
    except ValidationError as exc:
        raise SkillCatalogError(f"invalid skill {path}:\n{exc}") from exc
    if skill.name != directory.name:
        raise SkillCatalogError(f"{path}: name {skill.name!r} is not the directory's name")
    return skill


def load_skills(root: Path = SKILLS_DIR) -> dict[str, Skill]:
    """Every skill under `root`, by name; directories without SKILL.md are not skills."""
    found = sorted(path.parent for path in root.glob(f"*/{SKILL_FILE}"))
    return {skill.name: skill for skill in map(parse_skill, found)}


@cache
def get_skills() -> dict[str, Skill]:
    return load_skills()


def skill_index() -> list[tuple[str, str]]:
    """(name, description) of every built-in skill, in name order."""
    return [(skill.name, skill.description) for skill in get_skills().values()]


def load_skill(name: str) -> Skill:
    """The built-in skill called `name`; raises UnknownSkillError for any other string,
    paths included."""
    skill = get_skills().get(name)
    if skill is None:
        raise UnknownSkillError(f"no skill named {name!r}")
    return skill


def load_reference(name: str, part: str) -> str:
    """The text of `references/<part>.md` of the skill `name`; raises
    UnknownSkillError when there is no such skill or part."""
    text = load_skill(name).references.get(part)
    if text is None:
        raise UnknownSkillError(f"skill {name!r} has no part {part!r}")
    return text
