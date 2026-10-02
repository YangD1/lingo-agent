"""Filling practice slots from the placement item bank (ADR 0021 §3, Q33c).

Slots the generator could not fill (the critic rejected its drafts twice, the model
failed, or no model is configured) get a choice4 item from `placement/items.yaml`.
The bank has about one item per KC, so each slot looks, in order, for: an item on its
own KC the learner has not seen, one they last saw at least `practice.bank_repeat_days`
ago, then the same on the set's other weak KCs. Within a tier the item nearest the
slot's target difficulty wins, preferring a KC that does not sit next to the slot.
A slot nothing fits is dropped; the caller decides whether the set is still big enough.
"""

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import Choice4
from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.exercise.planner import target_difficulty
from app.adaptive.kc.catalog import GrammarKC
from app.adaptive.placement.flow import calibrated
from app.adaptive.placement.items import Item, ItemBank, get_item_bank
from app.adaptive.rules import Rules
from app.db.models import Exercise, PlacementItemStat, PlacementSession


@dataclass(frozen=True, slots=True)
class Slot:
    position: int
    kc_id: str


def fill(
    slots: Sequence[Slot],
    *,
    neighbours: Mapping[int, str],
    weak_kcs: Sequence[str],
    bank: ItemBank,
    seen: Mapping[str, datetime],
    ability: float,
    now: datetime,
    rules: Rules,
) -> dict[int, Item]:
    """Bank items for as many slots as possible, by position.

    `neighbours`: the KC at each position already filled, so a substitute avoids
    sitting next to its own KC. `weak_kcs`: the set's weak KCs, which may stand in for
    a slot whose KC has nothing usable. No bank item is used twice in a set.
    """
    target = target_difficulty(ability, "choice4", rules)
    repeat_before = now - timedelta(days=rules.practice.bank_repeat_days)
    by_kc: dict[str, list[Item]] = {}
    for item in bank.items:
        by_kc.setdefault(item.kc, []).append(item)
    placed = dict(neighbours)
    used: set[str] = set()
    out: dict[int, Item] = {}

    def usable(kc_ids: Sequence[str], fresh: bool) -> list[Item]:
        return [
            item
            for kc_id in kc_ids
            for item in by_kc.get(kc_id, [])
            if item.id not in used
            and (item.id not in seen if fresh else seen.get(item.id, now) <= repeat_before)
        ]

    for slot in sorted(slots, key=lambda s: s.position):
        near = {placed.get(slot.position - 1), placed.get(slot.position + 1)}
        others = [k for k in weak_kcs if k != slot.kc_id]
        for kc_ids, fresh in (
            ([slot.kc_id], True),
            ([slot.kc_id], False),
            (others, True),
            (others, False),
        ):
            if options := usable(kc_ids, fresh):
                best = min(options, key=lambda i: (i.kc in near, abs(i.difficulty - target), i.id))
                out[slot.position] = best
                placed[slot.position] = best.kc
                used.add(best.id)
                break
    return out


def explanation(kc: GrammarKC, answer: str, explain_in: ExplainIn) -> str:
    """Bank items carry no explanation; name the grammar point and the answer."""
    if explain_in == "en":
        return f"This tests {kc.name_en}: {kc.description} The answer is “{answer}”."
    return f"这题考“{kc.name_zh}”。正确答案是“{answer}”。"


def to_body(item: Item, kc: GrammarKC, explain_in: ExplainIn, rng: random.Random) -> Choice4:
    options = list(item.options)
    rng.shuffle(options)
    return Choice4.model_validate(
        {
            "content": {"stem": item.stem, "options": options},
            "answer": {
                "correct": item.answer,
                "explanation": explanation(kc, item.answer, explain_in),
            },
        }
    )


# --- from the database ---


async def load_bank(session: AsyncSession, rules: Rules) -> ItemBank:
    """The bank with difficulties re-estimated from enough placement answers, as the
    placement test uses it."""
    difficulties = dict(
        (
            await session.execute(
                select(PlacementItemStat.item_id, PlacementItemStat.difficulty).where(
                    PlacementItemStat.attempts >= rules.placement.grammar.calibrated_min_attempts
                )
            )
        ).all()
    )
    return calibrated(get_item_bank(), difficulties)


async def seen_items(session: AsyncSession, user_id: uuid.UUID) -> dict[str, datetime]:
    """When the learner last saw each bank item: in a finished placement test, or as a
    practice item (rejected ones were never shown)."""
    seen: dict[str, datetime] = {}
    tests = await session.execute(
        select(PlacementSession.result, PlacementSession.finished_at).where(
            PlacementSession.user_id == user_id, PlacementSession.status == "done"
        )
    )
    for result, finished_at in tests.all():
        for answer in result["answers"]["grammar"]:
            item_id = answer["item_id"]
            if item_id not in seen or seen[item_id] < finished_at:
                seen[item_id] = finished_at
    practice = await session.execute(
        select(Exercise.bank_item_id, func.max(Exercise.created_at))
        .where(
            Exercise.user_id == user_id,
            Exercise.bank_item_id.is_not(None),
            Exercise.status != "rejected",
        )
        .group_by(Exercise.bank_item_id)
    )
    for item_id, at in practice.all():
        assert item_id is not None  # filtered above
        if item_id not in seen or seen[item_id] < at:
            seen[item_id] = at
    return seen
