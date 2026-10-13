"""The route evaluator (task 68.1): `route_messages` -> the `route` task, as free chat
decides whether writing_coach takes a long message.

Each case is a message long enough to be classified (`worth_classifying`) and, maybe,
the end of the tutor's previous message. Metrics: `writing_found` (the learner's own
writing, to be reviewed, goes to writing_coach) and `chat_kept` (everything else stays
with the tutor: questions, chat, text the learner did not write).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents.routing import TASK, RouteDecision, route_messages, worth_classifying
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult


class RouteCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expect: Literal["tutor", "writing_coach"]
    text: str
    previous: str = ""


class RouteEval:
    name = "route"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        c = RouteCase.model_validate(case.data)
        if not worth_classifying(c.text):
            raise ValueError(f"{case.id}: too short to reach the classifier")
        out = await model.structured(
            case.id, TASK, RouteDecision, route_messages(c.text, c.previous)
        )
        metric = "writing_found" if c.expect == "writing_coach" else "chat_kept"
        return CaseResult(case.id, {metric: out.route == c.expect}, f"route: {out.route}")
