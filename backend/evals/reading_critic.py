"""The reading critic evaluator (task 68.1): `critic_messages` -> `reading_critic` ->
`rejection`, as comprehension questions are checked before a learner sees them.

Each case is one question on one of the dataset's articles (`articles` at the top of
the YAML), reviewed alone, with its options in a fixed order and its answer key; a
case fails exactly when the app would make the wrong call on it. Bad questions count
towards `bad_rejected` (and `rejects:<flaw>`), good ones towards `good_passed`.
"""

from functools import cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.reading.drafts import Question, QuestionReviews, rejection
from app.services.reading.messages import critic_messages
from app.services.reading.worker import CRITIC_TASK as TASK
from evals.dataset import DATASETS_DIR, Case
from evals.models import EvalModel
from evals.report import CaseResult

type Flaw = Literal["not_in_text", "two_right", "guessable", "unclear", "wrong_key"]


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: str
    title: str
    paragraphs: list[str] = Field(min_length=1)


class CriticCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    article: str
    expect: Literal["reject", "pass"]
    flaw: Flaw | None = None
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    answer: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def _flaw_iff_bad(self) -> "CriticCase":
        if (self.flaw is None) != (self.expect == "pass"):
            raise ValueError("a bad question names its flaw; a good one has none")
        return self


@cache
def articles() -> dict[str, Article]:
    raw = yaml.safe_load((DATASETS_DIR / "reading_critic.yaml").read_text(encoding="utf-8"))
    return {k: Article.model_validate(v) for k, v in raw["articles"].items()}


class ReadingCriticEval:
    name = "reading_critic"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        c = CriticCase.model_validate(case.data)
        article = articles()[c.article]
        question = Question(1, c.question, tuple(c.options), c.answer, evidence="")
        out = await model.structured(
            case.id,
            TASK,
            QuestionReviews,
            critic_messages(
                article.title, article.paragraphs, level=article.level, questions=[question]
            ),
        )
        review = next((r for r in out.reviews if r.position == 1), None)
        if review is None:
            raise ValueError("no review for the question")
        reasons = rejection(question, review)
        rejected = bool(reasons)
        checks = (
            {"bad_rejected": rejected, f"rejects:{c.flaw}": rejected}
            if c.expect == "reject"
            else {"good_passed": not rejected}
        )
        detail = f"own answer {review.own_answer} (key {c.answer}); " + (
            "; ".join(reasons) if reasons else "passed"
        )
        return CaseResult(case.id, checks, detail)
