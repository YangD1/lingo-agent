from pathlib import Path
from typing import Any

import pytest
import yaml

from app.speaking.scenarios import (
    ScenarioCatalogError,
    get_scenarios,
    load_scenarios,
)


def scenario(scenario_id: str, levels: list[str]) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "title_en": scenario_id,
        "title_zh": scenario_id,
        "levels": levels,
        "role": "A waiter.",
        "learner_goal_en": "Order.",
        "learner_goal_zh": "点餐。",
        "opening": "Greet the learner.",
    }


def write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "scenarios.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_shipped_file_is_valid() -> None:
    catalog = get_scenarios()
    ids = [s.id for s in catalog.scenarios]
    assert len(ids) == 10  # Q58h
    assert catalog.get("ordering_food") is not None
    assert all(s.target_expressions for s in catalog.scenarios)


def test_for_level_lists_suitable_first(tmp_path: Path) -> None:
    catalog = load_scenarios(
        write(
            tmp_path,
            {
                "scenarios": [
                    scenario("interview", ["B1", "C1"]),
                    scenario("intro", ["A1", "B1"]),
                    scenario("hotel", ["A2", "B1"]),
                ]
            },
        )
    )
    listed = catalog.for_level("A2")
    assert [(item.scenario.id, item.suits) for item in listed] == [
        ("intro", True),
        ("hotel", True),
        ("interview", False),
    ]
    assert [item.suits for item in catalog.for_level("C1")] == [True, False, False]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"scenarios": [scenario("a", ["B2", "A1"])]}, "lowest to highest"),
        ({"scenarios": [scenario("a", ["A1", "A2"]), scenario("a", ["A1", "A2"])]}, "duplicate"),
        ({"scenarios": [scenario("Bad-Id", ["A1", "A2"])]}, "invalid scenario file"),
        ({"scenarios": [{**scenario("a", ["A1", "A2"]), "extra": 1}]}, "invalid scenario file"),
        ({"scenarios": []}, "invalid scenario file"),
    ],
)
def test_rejects_invalid_files(tmp_path: Path, data: Any, message: str) -> None:
    with pytest.raises(ScenarioCatalogError, match=message):
        load_scenarios(write(tmp_path, data))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ScenarioCatalogError, match="not found"):
        load_scenarios(tmp_path / "nope.yaml")
