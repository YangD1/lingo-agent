from pathlib import Path

from evals.baseline import Baseline, diff, load_baselines, markdown, save_baselines
from evals.dataset import Case, Dataset
from evals.report import CaseResult, Report


def report(*checks: dict[str, bool]) -> Report:
    dataset = Dataset("toy", {"right": 0.5}, tuple(Case(str(i), {}) for i in range(len(checks))))
    return Report(dataset, [CaseResult(str(i), c) for i, c in enumerate(checks)])


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "baselines.json"
    saved = {"toy": Baseline({"right": (3, 4)}, ("m1",), "2026-10-13", {"route": "0a1b2c3d"})}
    save_baselines(saved, path)

    assert load_baselines(path) == saved
    assert '"right": [3, 4]' in path.read_text()
    assert load_baselines(tmp_path / "missing.json") == {}


def test_diff_names_changed_metrics_and_flags_drops() -> None:
    now = report({"right": True}, {"right": False})
    assert diff(now, Baseline({"right": (1, 2)})) == []
    assert diff(now, Baseline({"right": (2, 2)})) == ["  right: 2/2 -> 1/2  (-50 pts  WORSE)"]
    assert diff(now, Baseline({"right": (0, 2), "gone": (1, 1)})) == [
        "  right: 0/2 -> 1/2  (+50 pts)",
        "  gone: 1/1 -> -",
    ]
    assert diff(now, None) == ["  right: - -> 1/2"]


def test_markdown_marks_unmet_thresholds() -> None:
    table = markdown(
        {"toy": report({"right": False}, {"right": False})},
        {"toy": Baseline({"right": (0, 2)}, ("m1",), "2026-10-13")},
    )
    assert "| toy | right | 0/2 = 0% ❌ | 50% | m1 (2026-10-13) |" in table
