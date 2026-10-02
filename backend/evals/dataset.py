"""Datasets: YAML files of cases plus the accuracy each metric must reach."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DATASETS_DIR = Path(__file__).parent / "datasets"


class DatasetError(ValueError):
    """A dataset file that does not have the expected shape."""


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    # Everything else in the case: each evaluator reads its own fields.
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Dataset:
    name: str
    # Metric name -> the accuracy it must reach (Q36c: kept with the data, not in code).
    thresholds: Mapping[str, float]
    cases: Sequence[Case]


def parse_dataset(name: str, raw: object) -> Dataset:
    if not isinstance(raw, dict):
        raise DatasetError(f"{name}: expected a mapping at the top level")
    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, dict) or not all(
        isinstance(k, str) and isinstance(v, int | float) and 0 <= v <= 1
        for k, v in thresholds.items()
    ):
        raise DatasetError(f"{name}: thresholds must map metric names to 0..1")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise DatasetError(f"{name}: cases must be a non-empty list")
    cases: list[Case] = []
    seen: set[str] = set()
    for i, item in enumerate(raw_cases):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise DatasetError(f"{name}: case {i} needs a string id")
        case_id = item["id"]
        if case_id in seen:
            raise DatasetError(f"{name}: case id {case_id!r} repeats")
        seen.add(case_id)
        cases.append(Case(case_id, {k: v for k, v in item.items() if k != "id"}))
    return Dataset(name, {k: float(v) for k, v in thresholds.items()}, tuple(cases))


def load_dataset(name: str, directory: Path = DATASETS_DIR) -> Dataset:
    path = directory / f"{name}.yaml"
    return parse_dataset(name, yaml.safe_load(path.read_text(encoding="utf-8")))
