"""Every evaluation set, replayed from its recordings, meets its thresholds (Q36d)."""

import pytest

from evals.models import Cassette, ReplayModel
from evals.registry import EVALUATORS
from evals.runner import evaluate


@pytest.mark.parametrize("name", list(EVALUATORS))
async def test_meets_thresholds(name: str) -> None:
    report = await evaluate(EVALUATORS[name], ReplayModel(Cassette.load(name)))
    assert report.met, report.render()
