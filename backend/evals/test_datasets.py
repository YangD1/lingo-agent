"""Every case of every evaluation set is well formed: it gets as far as the model call."""

from collections.abc import Sequence

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from evals.registry import EVALUATORS
from evals.runner import evaluate


class Reached(Exception):
    pass


class StopAtTheModel:
    def __init__(self) -> None:
        self.prompts: dict[str, str] = {}

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        raise Reached


@pytest.mark.parametrize("name", list(EVALUATORS))
async def test_every_case_reaches_the_model(name: str) -> None:
    report = await evaluate(EVALUATORS[name], StopAtTheModel())
    assert all(r.error == "Reached: " for r in report.results), [
        (r.case_id, r.error) for r in report.results if r.error != "Reached: "
    ]
