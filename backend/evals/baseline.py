"""Score baselines: `baselines.json`, one entry per evaluation set (ADR 0033 §3).

Recording (`--live --record`) writes the new scores here, so a pull request that
re-records shows every score change in its diff. Replay is deterministic, so it must
reproduce the baseline exactly: a difference means the evaluator or its grading
changed without the baseline being updated (`--update-baseline`).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from evals.report import Report

BASELINES_PATH = Path(__file__).parent / "baselines.json"


@dataclass(frozen=True, slots=True)
class Baseline:
    # Metric name -> (hits, total).
    metrics: Mapping[str, tuple[int, int]]
    # The models the recording was made with (each task's first in its chain).
    models: tuple[str, ...] = ()
    # The day it was recorded, ISO format.
    recorded: str | None = None
    # `{prompt name: version}` the recorded calls used (ADR 0033 §2).
    prompts: Mapping[str, str] = field(default_factory=dict)


def scores(report: Report) -> dict[str, tuple[int, int]]:
    return {m.name: (m.hits, m.total) for m in report.metrics}


def load_baselines(path: Path = BASELINES_PATH) -> dict[str, Baseline]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: Baseline(
            metrics={k: (v[0], v[1]) for k, v in entry["metrics"].items()},
            models=tuple(entry.get("models", ())),
            recorded=entry.get("recorded"),
            prompts=entry.get("prompts", {}),
        )
        for name, entry in raw.items()
    }


def save_baselines(baselines: Mapping[str, Baseline], path: Path = BASELINES_PATH) -> None:
    raw = {
        name: {
            "metrics": {k: list(v) for k, v in b.metrics.items()},
            "models": list(b.models),
            "recorded": b.recorded,
            "prompts": dict(sorted(b.prompts.items())),
        }
        for name, b in sorted(baselines.items())
    }
    text = json.dumps(raw, ensure_ascii=False, indent=1)
    # One line per score: `"bad_rejected": [24, 26]`.
    text = re.sub(r"\[\s+(\d+),\s+(\d+)\s+\]", r"[\1, \2]", text)
    path.write_text(text + "\n", encoding="utf-8")


def diff(report: Report, baseline: Baseline | None) -> list[str]:
    """One line per metric whose score is not the baseline's; [] when all match."""
    now = scores(report)
    before = baseline.metrics if baseline is not None else {}
    lines = []
    for name in [*now, *(n for n in before if n not in now)]:
        new, old = now.get(name), before.get(name)
        if new == old:
            continue
        lines.append(f"  {name}: {_score(old)} -> {_score(new)}{_change(old, new)}")
    return lines


def _score(value: tuple[int, int] | None) -> str:
    return "-" if value is None else f"{value[0]}/{value[1]}"


def _change(old: tuple[int, int] | None, new: tuple[int, int] | None) -> str:
    if old is None or new is None or not old[1] or not new[1]:
        return ""
    points = (new[0] / new[1] - old[0] / old[1]) * 100
    if abs(points) < 0.5:
        return ""
    return f"  ({points:+.0f} pts{'  WORSE' if points < 0 else ''})"


def markdown(reports: Mapping[str, Report], baselines: Mapping[str, Baseline]) -> str:
    """A table for the CI job summary."""
    lines = [
        "| Set | Metric | Score | Threshold | Recorded with |",
        "|---|---|---|---|---|",
    ]
    for name, report in reports.items():
        b = baselines.get(name)
        recorded = f"{', '.join(b.models) or '?'} ({b.recorded or '?'})" if b else "-"
        for m in report.metrics:
            gate = "-" if m.threshold is None else f"{m.threshold:.0%}"
            mark = "" if m.met else " ❌"
            lines.append(
                f"| {name} | {m.name} | {m.hits}/{m.total} = {m.accuracy:.0%}{mark} "
                f"| {gate} | {recorded} |"
            )
    return "\n".join(lines)
