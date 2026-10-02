"""The messages of the `exercise_generate` and `exercise_critic` calls (ADR 0021 §3).

The system prompts live in `app/prompts/`; this module writes the per-set part. Each
item is introduced by its position, which both models echo back so drafts and reviews
are matched to their slot in code.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.adaptive.exercise.formats import SPECS, ExerciseBody, OpenAnswer
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs
from app.adaptive.rules import Rules
from app.prompts import load_prompt

_LANGUAGES = {"zh": "Simplified Chinese", "en": "English"}


@dataclass(frozen=True, slots=True)
class Rejected:
    """A draft the critic (or validation) turned down, sent back to be rewritten."""

    draft: Mapping[str, object]
    reasons: Sequence[str]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def rubric(rules: Rules) -> str:
    lines = []
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


def _brief(brief: ItemBrief, rules: Rules) -> dict[str, object]:
    kc = brief.kc
    out: dict[str, object] = {
        "position": brief.position,
        "format": brief.item.format,
        "grammar_point": {
            "id": kc.id,
            "name": kc.name_en,
            "level": kc.cefr,
            "description": kc.description,
            "common_errors": list(kc.common_errors),
        },
        "target_offset_sum": target_offset(brief, rules),
    }
    if brief.own_sentence is not None:
        out["learner_sentence"] = {
            "original": brief.own_sentence.original,
            "their_tutor_corrected_it_to": brief.own_sentence.correction,
        }
    return out


def generate_messages(
    briefs: Sequence[ItemBrief],
    learner: LearnerInputs,
    rules: Rules,
    rejected: Mapping[int, Rejected] | None = None,
) -> list[BaseMessage]:
    """Ask for drafts of `briefs`; with `rejected`, they are rewrites of those drafts."""
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
    parts.append("Difficulty rubric:\n" + rubric(rules))
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
    return [SystemMessage(load_prompt("exercise_generate")), HumanMessage("\n\n".join(parts))]


def shown(body: ExerciseBody) -> dict[str, object]:
    """What the critic sees of an item: what the learner sees, plus the reference
    answers of open formats, which it cannot judge otherwise. Closed formats keep their
    key hidden: code compares the critic's own answer with it."""
    content = body.content.model_dump(exclude={"evidence_id"}, exclude_none=True)
    out: dict[str, object] = {"format": body.format, "content": content}
    if SPECS[body.format].grading == "model" and isinstance(body.answer, OpenAnswer):
        out["reference_answers"] = list(body.answer.accepted)
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
    return [SystemMessage(load_prompt("exercise_critic")), HumanMessage("\n\n".join(parts))]
