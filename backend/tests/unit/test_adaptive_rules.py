from pathlib import Path
from typing import Any

import pytest
import yaml

from app.adaptive.rules import RULES_PATH, RulesError, load_rules


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return data


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_shipped_rules_load() -> None:
    rules = load_rules()
    assert rules.version
    assert rules.bkt.p_guess["production"] < rules.bkt.p_guess["recognition"]
    assert "low" not in rules.evidence.counted_severities
    assert rules.elo.guess_by_format["choice4"] == 0.25


def _set(data: dict[str, Any], path: str, value: Any) -> None:
    *parents, last = path.split(".")
    for key in parents:
        data = data[key]
    if value is None:
        del data[last]
    else:
        data[last] = value


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("bkt.p_learn", 1.5, "less than or equal to 1"),
        ("bkt.p_slip", 0.0, "greater than 0"),
        ("bkt.p_guess", {"recognition": 0.2}, "missing \\['production'\\]"),
        ("bkt.p_guess", {"recognition": 0.95, "production": 0.05}, "must be below 1"),
        ("bkt.prior_by_gap", {2: 0.9, 0: 0.4}, "consecutive"),
        ("bkt.prior_unknown_learner", {"A1": 0.6}, "missing"),
        ("bkt.weak", 0.95, "weak must be below mastered"),
        ("vocab.desired_retention", 1.0, "less than 1"),
        ("vocab.screening.window", 10, "at least batch_size"),
        ("evidence.counted_severities", ["medium", "fatal"], "counted_severities"),
        ("evidence.max_per_turn", 0, "greater than or equal to 1"),
        ("elo.learner.alpha", 0, "greater than 0"),
        ("difficulty.cefr_anchor.C2", -9.0, "must not decrease"),
        ("placement.vocab.max_rank", 20500, "multiple of band_size"),
        ("placement.vocab.pseudo_share", 1.0, "less than 1"),
        ("version", None, "version"),
        ("elo.unknown", 1, "Extra inputs"),
    ],
)
def test_rejects_invalid_rules(tmp_path: Path, path: str, value: Any, message: str) -> None:
    data = raw()
    _set(data, path, value)
    with pytest.raises(RulesError, match=message):
        load_rules(write(tmp_path, data))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="not found"):
        load_rules(tmp_path / "nope.yaml")
