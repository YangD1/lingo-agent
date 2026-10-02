"""The critic evaluation set and evaluator (task 36.2), with scripted critics."""

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, get_args

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.adaptive.exercise.formats import FORMATS, Choice4, Cloze, FindFix
from app.adaptive.exercise.worker import CRITIC_TASK
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from evals.critic import POSITION, CriticEval, Flaw, Item, make_item
from evals.dataset import load_dataset
from evals.runner import evaluate

DATASET = load_dataset("critic")
RULES = get_rules()
ITEMS = {c.id: make_item(c.data, RULES, get_grammar_catalog()) for c in DATASET.cases}

# What a review says about an item: (answer_ok, tests_kc, content_ok, ratings).
Opinion = Callable[[Item], tuple[bool, bool, bool, dict[str, str]]]


def key_answer(item: Item) -> tuple[str, int | None]:
    """The answer the item's key gives, as the critic would write it."""
    match item.body:
        case Choice4():
            return item.body.answer.correct, None
        case Cloze():
            return item.body.answer.accepted[0], None
        case FindFix():
            return item.body.answer.accepted[0], item.body.answer.wrong_segment
    return item.body.answer.accepted[0], None


def opposite(ratings: dict[str, str]) -> dict[str, str]:
    """The other end of each rubric dimension."""
    out = {}
    for name, level in ratings.items():
        levels = list(RULES.difficulty.dimensions[name].levels)
        out[name] = levels[-1] if levels.index(level) < len(levels) / 2 else levels[0]
    return out


def ideal(item: Item) -> tuple[bool, bool, bool, dict[str, str]]:
    flaw = item.case.flaw
    ratings = opposite(item.case.ratings) if flaw == "misrated" else item.case.ratings
    return (
        flaw not in ("wrong_key", "two_right"),
        flaw != "off_target",
        flaw not in ("unnatural", "factual"),
        ratings,
    )


def rubber_stamp(item: Item) -> tuple[bool, bool, bool, dict[str, str]]:
    return True, True, True, item.case.ratings


class ScriptedCritic:
    """Reviews each case's item as `opinion` says, answering it as its key does."""

    def __init__(self, opinion: Opinion, skip: Sequence[str] = ()) -> None:
        self.opinion = opinion
        self.skip = skip
        self.calls: list[tuple[str, str, int]] = []

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        self.calls.append((case_id, task, len(messages)))
        item = ITEMS[case_id]
        answer_ok, tests_kc, content_ok, ratings = self.opinion(item)
        own_answer, own_segment = key_answer(item)
        review: dict[str, Any] = {
            "position": POSITION,
            "own_answer": own_answer,
            "own_segment": own_segment,
            "answer_ok": answer_ok,
            "tests_kc": tests_kc,
            "content_ok": content_ok,
            "problems": [] if answer_ok and tests_kc and content_ok else ["scripted"],
            "ratings": {k: {"level": v, "reason": "scripted"} for k, v in ratings.items()},
        }
        return schema.model_validate({"reviews": [] if case_id in self.skip else [review]})


def test_the_set_covers_every_flaw_and_format() -> None:
    bad = [i for i in ITEMS.values() if i.case.expect == "reject"]
    good = [i for i in ITEMS.values() if i.case.expect == "pass"]
    # With a 90% gate, at least 10 a side lets one miss through and no more.
    assert len(bad) >= 10 and len(good) >= 10
    assert set(DATASET.thresholds) == {"bad_rejected", "good_passed"}
    flaws = Counter(i.case.flaw for i in bad)
    assert set(flaws) == set(get_args(Flaw.__value__)) and min(flaws.values()) >= 3
    assert {i.case.format for i in good} == set(FORMATS)
    assert {i.case.format for i in bad} == set(FORMATS)


async def test_an_ideal_critic_meets_every_threshold() -> None:
    critic = ScriptedCritic(ideal)
    report = await evaluate(CriticEval(), critic, DATASET)
    assert report.met, report.render()
    assert all(r.passed for r in report.results)
    assert {task for _, task, _ in critic.calls} == {CRITIC_TASK}
    by_name = {m.name: m for m in report.metrics}
    assert by_name["rejects:misrated"].hits == by_name["rejects:misrated"].total == 3


async def test_a_rubber_stamp_critic_fails_the_bad_items() -> None:
    report = await evaluate(CriticEval(), ScriptedCritic(rubber_stamp), DATASET)
    by_name = {m.name: m for m in report.metrics}
    assert by_name["good_passed"].accuracy == 1
    assert by_name["bad_rejected"].hits == 0
    assert not report.met
    failed = next(r for r in report.results if r.case_id == "choice4-sun-rises-in-the-west")
    assert failed.detail == "passed"


async def test_a_skipped_review_fails_the_case() -> None:
    report = await evaluate(
        CriticEval(), ScriptedCritic(ideal, skip=["good-choice4-since"]), DATASET
    )
    failed = [r for r in report.results if not r.passed]
    assert [r.case_id for r in failed] == ["good-choice4-since"]
    assert failed[0].detail == "the critic returned no review for the item"


def test_bad_cases_are_refused() -> None:
    good = DATASET.cases[-1].data
    with pytest.raises(ValueError, match="flaw"):
        make_item({**good, "flaw": "factual"}, RULES, get_grammar_catalog())
    with pytest.raises(ValueError, match="unknown grammar KC"):
        make_item({**good, "kc": "g.nope"}, RULES, get_grammar_catalog())
