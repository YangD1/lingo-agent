"""The evaluation framework (task 36.1): datasets, reports, record and replay."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from evals import models
from evals.dataset import Case, DatasetError, load_dataset, parse_dataset
from evals.models import Cassette, CassetteMiss, EvalModel, LiveModel, ReplayModel, call_key
from evals.report import CaseResult, Report
from evals.runner import evaluate


class Answer(BaseModel):
    value: str


class Echo:
    """A toy evaluator: the model must answer each case's `expect`."""

    name = "echo"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        out = await model.structured(case.id, "toy", Answer, messages_for(case))
        if case.data.get("boom"):
            raise RuntimeError("model said nonsense")
        return CaseResult(case.id, {"right": out.value == case.data["expect"]}, out.value)


def messages_for(case: Case) -> list[BaseMessage]:
    return [SystemMessage("Answer."), HumanMessage(str(case.data["q"]))]


DATASET = parse_dataset(
    "echo",
    {
        "thresholds": {"right": 0.5},
        "cases": [
            {"id": "a", "q": "one", "expect": "1"},
            {"id": "b", "q": "two", "expect": "2"},
        ],
    },
)


def cassette_for(path: Path, outputs: dict[str, str]) -> Cassette:
    cassette = Cassette(path)
    for case in DATASET.cases:
        if case.id in outputs:
            msgs = messages_for(case)
            key = call_key("toy", Answer, msgs)
            cassette.add(case.id, "toy", key, Answer(value=outputs[case.id]))
    return cassette


# --- datasets ---


def test_dataset_round_trip(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text(
        "thresholds: {hit: 0.9}\ncases:\n  - id: c1\n    text: hi\n", encoding="utf-8"
    )
    ds = load_dataset("x", tmp_path)
    assert ds.thresholds == {"hit": 0.9}
    assert ds.cases == (Case("c1", {"text": "hi"}),)


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"cases": []},
        {"cases": [{"text": "no id"}]},
        {"cases": [{"id": "a"}, {"id": "a"}]},
        {"thresholds": {"hit": 1.5}, "cases": [{"id": "a"}]},
        {"thresholds": ["hit"], "cases": [{"id": "a"}]},
    ],
)
def test_bad_datasets_are_refused(raw: Any) -> None:
    with pytest.raises(DatasetError):
        parse_dataset("x", raw)


# --- reports ---


def test_report_metrics_and_thresholds() -> None:
    ds = parse_dataset(
        "r", {"thresholds": {"bad_rejected": 0.9}, "cases": [{"id": str(i)} for i in range(4)]}
    )
    results = [
        CaseResult("0", {"bad_rejected": True}),
        CaseResult("1", {"bad_rejected": False}, detail="critic passed it"),
        CaseResult("2", {"good_passed": True}),
        CaseResult("3", {"good_passed": True}),
    ]
    report = Report(ds, results)
    by_name = {m.name: m for m in report.metrics}
    # Only cases with a metric count towards it; ungated metrics are reported too.
    assert (by_name["bad_rejected"].hits, by_name["bad_rejected"].total) == (1, 2)
    assert (by_name["good_passed"].hits, by_name["good_passed"].total) == (2, 2)
    assert not report.met
    assert report.unmet() == ["bad_rejected: 1/2 = 50% < 90%"]
    text = report.render()
    assert "FAIL 1" in text and "critic passed it" in text and "NOT MET" in text


def test_a_gated_metric_no_case_has_is_not_met() -> None:
    ds = parse_dataset("r", {"thresholds": {"hit": 0.5}, "cases": [{"id": "a"}]})
    assert not Report(ds, [CaseResult("a", {"other": True})]).met


def test_errors_fail_the_report() -> None:
    ds = parse_dataset("r", {"cases": [{"id": "a"}]})
    report = Report(ds, [CaseResult("a", {}, error="TimeoutError: ")])
    assert not report.met
    assert not report.results[0].passed
    assert report.unmet() == ["a: call failed: TimeoutError: "]


# --- record and replay ---


def test_call_key_tracks_task_messages_and_schema() -> None:
    msgs = [SystemMessage("s"), HumanMessage("h")]

    class Other(BaseModel):
        value: int

    key = call_key("toy", Answer, msgs)
    assert key == call_key("toy", Answer, [SystemMessage("s"), HumanMessage("h")])
    assert key != call_key("other", Answer, msgs)
    assert key != call_key("toy", Other, msgs)
    assert key != call_key("toy", Answer, [SystemMessage("s"), HumanMessage("h!")])
    assert key != call_key("toy", Answer, [HumanMessage("s"), HumanMessage("h")])


async def test_replay_scores_recorded_outputs(tmp_path: Path) -> None:
    cassette = cassette_for(tmp_path / "echo.json", {"a": "1", "b": "3"})
    cassette.save()
    report = await evaluate(Echo(), ReplayModel(Cassette.load("echo", tmp_path)), DATASET)
    assert [r.passed for r in report.results] == [True, False]
    assert report.met  # 50% meets 0.5


async def test_replay_miss_stops_the_run(tmp_path: Path) -> None:
    cassette = cassette_for(tmp_path / "echo.json", {"a": "1"})
    with pytest.raises(CassetteMiss, match=r"echo/b: .*re-record with make eval-live"):
        await evaluate(Echo(), ReplayModel(cassette), DATASET)


async def test_other_failures_count_against_their_case(tmp_path: Path) -> None:
    ds = parse_dataset("echo", {"cases": [{"id": "a", "q": "one", "expect": "1", "boom": True}]})
    cassette = Cassette(tmp_path / "echo.json")
    cassette.add("a", "toy", call_key("toy", Answer, messages_for(ds.cases[0])), Answer(value="1"))
    report = await evaluate(Echo(), ReplayModel(cassette), ds)
    assert report.results[0].error == "RuntimeError: model said nonsense"


class FakeStructured:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> Answer:
        return Answer(value=self.answers[str(messages[-1].content)])


async def test_live_records_what_replay_then_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, str]] = []

    def fake_get_structured_llm(ctx: object, task: str, schema: type) -> FakeStructured:
        calls.append((ctx, task))
        return FakeStructured({"one": "1", "two": "2"})

    monkeypatch.setattr(models, "get_structured_llm", fake_get_structured_llm)
    # A stale recording that no case makes any more.
    (tmp_path / "echo.json").write_text(json.dumps({"stale": {"output": {}}}), encoding="utf-8")

    ctx = object()
    record_to = Cassette(tmp_path / "echo.json")
    live = await evaluate(Echo(), LiveModel(ctx, record_to), DATASET)  # type: ignore[arg-type]
    record_to.save()
    assert live.met and calls == [(ctx, "toy"), (ctx, "toy")]

    saved = json.loads((tmp_path / "echo.json").read_text(encoding="utf-8"))
    assert "stale" not in saved
    assert {e["case"] for e in saved.values()} == {"a", "b"}
    assert {e["task"] for e in saved.values()} == {"toy"}

    replayed = await evaluate(Echo(), ReplayModel(Cassette.load("echo", tmp_path)), DATASET)
    assert [r.passed for r in replayed.results] == [True, True]
