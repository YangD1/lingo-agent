"""Every evaluation set, replayed from its recordings, meets its thresholds (Q36d)."""

import pytest

from evals.models import RERECORD_HINT, Cassette, ReplayModel
from evals.registry import EVALUATORS
from evals.runner import evaluate


@pytest.mark.parametrize("name", list(EVALUATORS))
async def test_meets_thresholds(name: str) -> None:
    cassette = Cassette.load(name)
    if not cassette.path.exists():
        pytest.skip(f"{name} has no recordings yet: record them with {RERECORD_HINT}")
    report = await evaluate(EVALUATORS[name], ReplayModel(cassette))
    assert report.met, report.render()
