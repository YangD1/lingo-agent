"""Running an evaluator over its dataset."""

import asyncio
from typing import Protocol

from evals.dataset import Case, Dataset, load_dataset
from evals.models import CassetteMiss, EvalModel
from evals.report import CaseResult, Report


class Evaluator(Protocol):
    # Also the stem of its dataset and cassette files.
    name: str

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult: ...


async def evaluate(
    evaluator: Evaluator,
    model: EvalModel,
    dataset: Dataset | None = None,
    concurrency: int = 4,
) -> Report:
    """Run every case, `concurrency` at a time. A replay miss stops the run (the
    recordings are stale); any other failure counts against that case only."""
    dataset = dataset or load_dataset(evaluator.name)
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> CaseResult:
        async with gate:
            try:
                return await evaluator.run_case(case, model)
            except CassetteMiss:
                raise
            except Exception as e:
                return CaseResult(case.id, {}, error=f"{type(e).__name__}: {e}")

    results = await asyncio.gather(*(one(c) for c in dataset.cases))
    return Report(dataset, results)
