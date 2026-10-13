"""The writing review evaluator (task 68.1): `review_messages` -> `writing_review` ->
`check`, as a piece of writing is reviewed and its mistakes become evidence.

Each case is a text split into sentences as the app splits it (`sentences`). Metrics,
on what `check` keeps:

- `mistakes_found`: each expected mistake is kept, in its sentence (counted from 0),
  on one of the acceptable KCs, quoting the given words.
- `correct_left_alone`: a sentence with no mistake gets no kept mistake and is not
  rewritten.
- `quotes_hold`: every mistake the model gave quotes its own sentence and names a
  catalog KC (`check` dropped none), so no evidence comes from text the learner did
  not write.
- `no_unchanged` (no threshold): the model listed no correct part as a mistake (a
  correction equal to the original; `check` drops those too, so they never become
  evidence).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.kc.catalog import get_grammar_catalog
from app.writing.review import TASK, Review, check, review_messages
from app.writing.text import sentences
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult


class ExpectedMistake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentence: int
    kcs: list[str] = Field(min_length=1)
    words: str


class ReviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: str = "B1"
    explain_in: Literal["zh", "en"] = "zh"
    prompt: str = ""
    text: str
    expect_mistakes: list[ExpectedMistake] = []
    correct_sentences: list[int] = []


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


class WritingReviewEval:
    name = "writing_review"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        c = ReviewCase.model_validate(case.data)
        catalog = get_grammar_catalog()
        parts = sentences(c.text)
        for m in c.expect_mistakes:
            if not 0 <= m.sentence < len(parts) or _fold(m.words) not in _fold(
                parts[m.sentence].text
            ):
                raise ValueError(f"{case.id}: {m.words!r} is not in sentence {m.sentence}")
            if unknown := [k for k in m.kcs if k not in catalog]:
                raise ValueError(f"{case.id}: unknown KC {unknown}")
        out = await model.structured(
            case.id, TASK, Review, review_messages(c.prompt, parts, c.level, c.explain_in)
        )
        checked = check(out, parts, catalog)
        rows = checked.corrections
        checks: dict[str, bool] = {}
        if c.expect_mistakes:
            checks["mistakes_found"] = all(
                any(
                    k["kc_id"] in m.kcs and _fold(m.words) in _fold(str(k["original"]))
                    for k in _mistakes(rows[m.sentence])
                )
                for m in c.expect_mistakes
            )
        if c.correct_sentences:
            checks["correct_left_alone"] = all(
                not _mistakes(rows[i]) and rows[i]["corrected"] is None for i in c.correct_sentences
            )
        checks["quotes_hold"] = checked.dropped == 0
        checks["no_unchanged"] = checked.unchanged == 0
        detail = "\n".join(
            f"[{r['index']}] {r['original']} -> {r['corrected']}"
            + "".join(
                f"\n      {k['kc_id']}: {k['original']} -> {k['correction']}" for k in _mistakes(r)
            )
            for r in rows
            if r["corrected"] is not None or _mistakes(r)
        )
        return CaseResult(case.id, checks, detail)


def _mistakes(row: dict[str, object]) -> list[dict[str, object]]:
    kept = row["mistakes"]
    assert isinstance(kept, list)
    return kept
