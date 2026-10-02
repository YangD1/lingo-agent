"""Per-case results and the summary checked against a dataset's thresholds."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from evals.dataset import Dataset


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    # Metric name -> whether this case got it right. A case counts only towards the
    # metrics it has (a good item has no "bad item rejected").
    checks: Mapping[str, bool]
    # What the model said, for reading a failure without rerunning.
    detail: str = ""
    # The call itself failed (live mode: the model gave no valid output).
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(self.checks.values())


@dataclass(frozen=True, slots=True)
class MetricSummary:
    name: str
    hits: int
    total: int
    threshold: float | None

    @property
    def accuracy(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def met(self) -> bool:
        return self.threshold is None or (self.total > 0 and self.accuracy >= self.threshold)


@dataclass(frozen=True, slots=True)
class Report:
    dataset: Dataset
    results: Sequence[CaseResult]
    metrics: Sequence[MetricSummary] = field(init=False)

    def __post_init__(self) -> None:
        names = list(self.dataset.thresholds)
        names += sorted({n for r in self.results for n in r.checks} - set(names))
        summaries = []
        for name in names:
            got = [r.checks[name] for r in self.results if name in r.checks]
            summaries.append(
                MetricSummary(name, sum(got), len(got), self.dataset.thresholds.get(name))
            )
        object.__setattr__(self, "metrics", tuple(summaries))

    @property
    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if r.error is not None]

    @property
    def met(self) -> bool:
        return not self.errors and all(m.met for m in self.metrics)

    def unmet(self) -> list[str]:
        out = [
            f"{m.name}: {m.hits}/{m.total} = {m.accuracy:.0%} < {m.threshold:.0%}"
            for m in self.metrics
            if not m.met and m.threshold is not None
        ]
        out += [f"{r.case_id}: call failed: {r.error}" for r in self.errors]
        return out

    def render(self) -> str:
        lines = [f"== {self.dataset.name} =="]
        for r in self.results:
            mark = "ok  " if r.passed else "FAIL"
            checks = ", ".join(f"{k}={'y' if v else 'n'}" for k, v in r.checks.items())
            lines.append(f"{mark} {r.case_id}  [{checks}]")
            if r.error is not None:
                lines.append(f"       error: {r.error}")
            if not r.passed and r.detail:
                lines.extend(f"       {line}" for line in r.detail.splitlines())
        for m in self.metrics:
            gate = "" if m.threshold is None else f"  (need {m.threshold:.0%})"
            status = "" if m.met else "  NOT MET"
            lines.append(f"  {m.name}: {m.hits}/{m.total} = {m.accuracy:.0%}{gate}{status}")
        return "\n".join(lines)
