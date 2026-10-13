"""Every evaluation set, replayed from its recordings, meets its thresholds (Q36d) and
reproduces its score baseline exactly (ADR 0033 §3)."""

import pytest

from evals.baseline import diff, load_baselines
from evals.models import RERECORD_HINT, Cassette, ReplayModel
from evals.registry import EVALUATORS
from evals.runner import evaluate


@pytest.mark.parametrize("name", list(EVALUATORS))
async def test_meets_thresholds_and_baseline(name: str) -> None:
    cassette = Cassette.load(name)
    if not cassette.path.exists():
        pytest.skip(f"{name} has no recordings yet: record them with {RERECORD_HINT}")
    model = ReplayModel(cassette)
    report = await evaluate(EVALUATORS[name], model)
    assert report.met, report.render()
    baseline = load_baselines().get(name)
    changed = diff(report, baseline)
    assert not changed, (
        f"{name} replays to other scores than its baseline; re-record, or accept them "
        "with `make eval ARGS='--update-baseline'`:\n" + "\n".join(changed)
    )
    assert baseline is not None and dict(baseline.prompts) == model.prompts
