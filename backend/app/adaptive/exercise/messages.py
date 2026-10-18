"""The messages of the `exercise_generate` and `exercise_critic` calls (ADR 0021 §3).

The system prompts live in `app/prompts/`; the generator's also carries the
`exercise-writing` skill, with the guides of only the formats in the set (ADR 0055 §2).
This module writes the per-set part. Each item is introduced by its position, which both
models echo back so drafts and reviews are matched to their slot in code.
"""

import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.adaptive.exercise import drafts
from app.adaptive.exercise.formats import (
    CHECK_FORMATS,
    FORMATS,
    SPECS,
    ExerciseBody,
    Explain,
    Format,
    OpenAnswer,
)
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs
from app.adaptive.placement.items import Item, ItemBank
from app.adaptive.rules import Rules
from app.prompts import load_prompt
from app.skills import load_reference, load_skill

_LANGUAGES = {"zh": "Simplified Chinese", "en": "English"}
SKILL = "exercise-writing"
# The skill's part on understanding checks, before the guides of their formats.
CHECKS_PART = "understanding-checks"
# Bank items shown per grammar point as examples of level and style.
EXAMPLES_PER_KC = 2


@dataclass(frozen=True, slots=True)
class Rejected:
    """A draft the critic (or validation) turned down, sent back to be rewritten."""

    draft: Mapping[str, object]
    reasons: Sequence[str]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def rubric(rules: Rules) -> str:
    lines: list[str] = []
    for name, dim in rules.difficulty.dimensions.items():
        lines.append(f"- {name}: {dim.description}")
        lines.extend(
            f"  - {level} ({spec.offset:+.1f}): {spec.description}"
            for level, spec in dim.levels.items()
        )
    return "\n".join(lines)


def _offset_range(rules: Rules) -> tuple[float, float]:
    dims = rules.difficulty.dimensions.values()
    return (
        sum(min(level.offset for level in d.levels.values()) for d in dims),
        sum(max(level.offset for level in d.levels.values()) for d in dims),
    )


def target_offset(brief: ItemBrief, rules: Rules) -> float:
    """The sum of rubric offsets that puts the item at its target difficulty, within
    what the rubric can reach."""
    low, high = _offset_range(rules)
    wanted = brief.item.target_difficulty - rules.difficulty.cefr_anchor[brief.kc.cefr]
    return round(min(max(wanted, low), high), 1)


def target_levels(brief: ItemBrief, rules: Rules) -> dict[str, str]:
    """One rubric level per dimension whose offsets add up closest to `target_offset`;
    of equally close ones, the first in rules.yaml order."""
    dims = rules.difficulty.dimensions
    wanted = target_offset(brief, rules)
    best = min(
        itertools.product(*(d.levels.items() for d in dims.values())),
        key=lambda combo: abs(sum(spec.offset for _, spec in combo) - wanted),
    )
    return {name: level for name, (level, _) in zip(dims, best, strict=True)}


def difficulty_target(brief: ItemBrief, rules: Rules) -> str:
    """The generator's difficulty target in words (ADR 0055 §4): what to aim for on each
    rubric dimension, saying so when the target is past what the rubric can reach, so the
    model does not try to go further."""
    low, high = _offset_range(rules)
    wanted = brief.item.target_difficulty - rules.difficulty.cefr_anchor[brief.kc.cefr]
    dims = rules.difficulty.dimensions
    aims = "; ".join(
        f"{name}: {dims[name].levels[level].description.rstrip('.')}"
        for name, level in target_levels(brief, rules).items()
    )
    if wanted <= low:
        return f"The easiest item this grammar point allows - that is already the target. {aims}."
    if wanted >= high:
        return f"The hardest item this grammar point allows - that is already the target. {aims}."
    return f"Aim for: {aims}."


def _brief(brief: ItemBrief, rules: Rules) -> dict[str, object]:
    kc = brief.kc
    out: dict[str, object] = {
        "position": brief.position,
        "format": brief.item.format,
        "fields": drafts.fields_of(brief.item.format),
        "grammar_point": {
            "id": kc.id,
            "name": kc.name_en,
            "level": kc.cefr,
            "description": kc.description,
            "common_errors": list(kc.common_errors),
        },
        "difficulty": difficulty_target(brief, rules),
    }
    if brief.own_sentence is not None:
        out["learner_sentence"] = {
            "original": brief.own_sentence.original,
            "their_tutor_corrected_it_to": brief.own_sentence.correction,
        }
    return out


def _system(name: str, formats: Sequence[str]) -> SystemMessage:
    """The critic's prompt, plus its part on understanding checks when the set has any
    (ADR 0044 §3), so practice sets keep the prompt they always had."""
    text = load_prompt(name)
    if any(f in CHECK_FORMATS for f in formats):
        text += "\n\n" + load_prompt(f"{name}_check")
    return SystemMessage(text)


def format_part(fmt: Format) -> str:
    """The skill reference with the guide to `fmt` (skill part names use hyphens)."""
    return fmt.replace("_", "-")


def writing_guide(formats: Sequence[str]) -> str:
    """The exercise-writing skill: its general rules, then the guides of `formats` in
    catalog order, the part on understanding checks first when there are any."""
    used = [f for f in FORMATS if f in formats]
    parts = [load_skill(SKILL).body]
    if any(f in CHECK_FORMATS for f in used):
        parts.append(load_reference(SKILL, CHECKS_PART))
    parts.extend(load_reference(SKILL, format_part(f)) for f in used)
    return "\n\n".join(parts)


def _examples(briefs: Sequence[ItemBrief], bank: ItemBank) -> list[str]:
    """Up to EXAMPLES_PER_KC bank items per grammar point of the set, those closest to
    its items' target difficulty first; none for a grammar point the bank lacks."""
    targets: dict[str, list[float]] = {}
    for b in briefs:
        targets.setdefault(b.kc.id, []).append(b.item.target_difficulty)
    lines: list[str] = []
    for kc_id, wanted in targets.items():
        aim = sum(wanted) / len(wanted)
        items: list[Item] = sorted(
            (i for i in bank.items if i.kc == kc_id), key=lambda i: (abs(i.difficulty - aim), i.id)
        )
        lines.extend(
            f"- {kc_id}: {i.stem} -> {i.answer} (wrong: {', '.join(i.distractors)})"
            for i in items[:EXAMPLES_PER_KC]
        )
    return lines


def generate_messages(
    briefs: Sequence[ItemBrief],
    learner: LearnerInputs,
    rules: Rules,
    rejected: Mapping[int, Rejected] | None = None,
    *,
    bank: ItemBank | None = None,
) -> list[BaseMessage]:
    """Ask for drafts of `briefs`; with `rejected`, they are rewrites of those drafts.
    With `bank`, its items on the set's grammar points are shown as examples."""
    parts = [
        f"Learner's level (CEFR): {learner.level or rules.practice.default_level}",
        f"Write explanations and translate sources in: {_LANGUAGES[learner.explain_in]}",
    ]
    personal = [f"{k}: {v}" for k, v in learner.profile.items()] + list(learner.facts)
    if personal:
        parts.append(
            "About the learner (use where it fits naturally):\n"
            + "\n".join(f"- {line}" for line in personal)
        )
    if bank is not None and (examples := _examples(briefs, bank)):
        parts.append(
            "Example items from the reviewed bank (four-option gap fills; level and style "
            "only, do not reuse them):\n" + "\n".join(examples)
        )
    parts.append("Items to write:\n" + _json([_brief(b, rules) for b in briefs]))
    if rejected:
        parts.append(
            "These drafts were rejected. Write a new item for each of these positions, "
            "fixing the problems:\n"
            + _json(
                [
                    {"position": p, "rejected_draft": r.draft, "problems": list(r.reasons)}
                    for p, r in sorted(rejected.items())
                ]
            )
        )
    guide = writing_guide([b.item.format for b in briefs])
    system = SystemMessage(load_prompt("exercise_generate") + "\n\n" + guide)
    return [system, HumanMessage("\n\n".join(parts))]


def shown(body: ExerciseBody) -> dict[str, object]:
    """What the critic sees of an item: what the learner sees, plus the reference
    answers of open formats, which it cannot judge otherwise. Closed formats keep their
    key hidden: code compares the critic's own answer with it."""
    content = body.content.model_dump(exclude={"evidence_id"}, exclude_none=True)
    out: dict[str, object] = {"format": body.format, "content": content}
    if SPECS[body.format].grading == "model" and isinstance(body.answer, OpenAnswer):
        out["reference_answers"] = list(body.answer.accepted)
    if isinstance(body, Explain):
        out["key_points"] = list(body.answer.key_points)
    return out


def critic_messages(
    items: Sequence[tuple[ItemBrief, ExerciseBody]], learner: LearnerInputs, rules: Rules
) -> list[BaseMessage]:
    reviewed = [
        {
            "position": brief.position,
            "grammar_point": {
                "name": brief.kc.name_en,
                "level": brief.kc.cefr,
                "description": brief.kc.description,
            },
            **shown(body),
        }
        for brief, body in items
    ]
    parts = [
        f"Learner's level (CEFR): {learner.level or rules.practice.default_level}",
        "Difficulty rubric:\n" + rubric(rules),
        "Items to review:\n" + _json(reviewed),
    ]
    system = _system("exercise_critic", [b.item.format for b, _ in items])
    return [system, HumanMessage("\n\n".join(parts))]
