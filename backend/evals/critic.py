"""The critic evaluator (task 36.2): `critic_messages` -> `exercise_critic` -> `judge`.

Each case is one item reviewed alone, with the generator's ratings from the dataset,
so a case fails exactly when the app would turn the item down. Bad items count towards
`bad_rejected` (and `rejects:<flaw>`, to see which kind slips through), good ones
towards `good_passed`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.adaptive.elo import prior_difficulty
from app.adaptive.exercise import drafts
from app.adaptive.exercise.formats import ExerciseBody, Format, parse_body
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs
from app.adaptive.exercise.messages import critic_messages
from app.adaptive.exercise.planner import PlannedItem
from app.adaptive.exercise.worker import CRITIC_TASK
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, GrammarKC, get_grammar_catalog
from app.adaptive.rules import Rules, get_rules
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult

type Flaw = Literal["wrong_key", "two_right", "off_target", "unnatural", "factual", "misrated"]

# One item per review, as the first item of a set.
POSITION = 1


class CriticCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expect: Literal["reject", "pass"]
    flaw: Flaw | None = None
    kc: str
    level: CefrLevel | None = None
    ratings: dict[str, str]
    format: Format
    content: dict[str, Any]
    answer: dict[str, Any]

    @model_validator(mode="after")
    def _flaw_iff_bad(self) -> "CriticCase":
        if (self.flaw is None) != (self.expect == "pass"):
            raise ValueError("a bad item names its flaw; a good one has none")
        return self


@dataclass(frozen=True, slots=True)
class Item:
    """A case made into what the critic node works with."""

    case: CriticCase
    kc: GrammarKC
    body: ExerciseBody
    generator_difficulty: float


def make_item(data: Mapping[str, Any], rules: Rules, catalog: GrammarCatalog) -> Item:
    case = CriticCase.model_validate(data)
    kc = catalog.get(case.kc)
    if kc is None:
        raise ValueError(f"unknown grammar KC {case.kc}")
    content = dict(case.content)
    if case.format == "rewrite_own":
        content.setdefault("evidence_id", 1)
    body = parse_body(case.format, content, case.answer)
    return Item(
        case=case,
        kc=kc,
        body=body,
        generator_difficulty=prior_difficulty(kc.cefr, case.ratings, rules),
    )


class CriticEval:
    name = "critic"

    def __init__(self, rules: Rules | None = None, catalog: GrammarCatalog | None = None) -> None:
        self.rules = rules or get_rules()
        self.catalog = catalog or get_grammar_catalog()

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        item = make_item(case.data, self.rules, self.catalog)
        brief = ItemBrief(
            POSITION,
            PlannedItem(item.kc.id, item.case.format, item.generator_difficulty, "weak"),
            item.kc,
        )
        learner = LearnerInputs(
            level=item.case.level or item.kc.cefr,
            ability=0.0,
            states={},
            own_sentences={},
            profile={},
            facts=(),
        )
        report = await model.structured(
            case.id,
            CRITIC_TASK,
            drafts.critic_report_model(self.rules),
            critic_messages([(brief, item.body)], learner, self.rules),
        )
        review = drafts.by_position(drafts.reviews_in(report), [POSITION]).get(POSITION)
        if review is None:
            passed, detail = False, "the critic returned no review for the item"
        else:
            verdict = drafts.judge(
                item.body, item.kc, item.generator_difficulty, review, self.rules
            )
            passed = verdict.ok
            detail = "passed" if verdict.ok else "; ".join(verdict.reasons)
        if item.case.flaw is None:
            return CaseResult(case.id, {"good_passed": passed}, detail)
        rejected = not passed
        checks = {"bad_rejected": rejected, f"rejects:{item.case.flaw}": rejected}
        return CaseResult(case.id, checks, detail)
