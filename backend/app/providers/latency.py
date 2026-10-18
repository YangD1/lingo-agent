"""How long a model usually takes, to tell a stalled call from a slow one (ADR 0056 §1).

A call is stalled when the vendor sends nothing for longer than the model's own recent
p95 times `factor`, kept within [`floor`, max(`ceiling`, the configured timeout)]: a
fast model's hang is found in seconds, and a thinking model that is always slow is not
cut off. Streamed calls are timed to their first chunk (and each gap after it), the rest
to the whole call. Without `min_samples` recent successful calls, the configured timeout
is used.

Each process keeps the last `window` successful calls per (tenant, connection, model,
task), and per (model, task) over all tenants, in memory: fed by every usage record,
seeded from `llm_usage` at start-up. A tenant's own calls are used once there are
enough of them; until then everyone's on the same model and task (every learner is a
tenant, and would otherwise wait for a fixed timeout through their first sets).
"""

import math
import uuid
from collections import deque
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage
from app.usage.recorder import UsageRecord


@dataclass(frozen=True, slots=True)
class StallRule:
    factor: float = 3.0
    floor: float = 20.0
    ceiling: float = 120.0
    min_samples: int = 10
    window: int = 200


class LatencyKey(NamedTuple):
    tenant_id: uuid.UUID
    connection: str
    model: str
    task: str

    @property
    def shared(self) -> tuple[str, str]:
        return self.model, self.task


def p95(samples: Sequence[float]) -> float:
    """Nearest-rank 95th percentile of a non-empty sample."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def stall_threshold(samples_ms: Sequence[int], configured: float, rule: StallRule) -> float:
    """Seconds without output after which a call counts as stalled."""
    if len(samples_ms) < rule.min_samples:
        return configured
    usual = p95(samples_ms) / 1000 * rule.factor
    return min(max(usual, rule.floor), max(rule.ceiling, configured))


class LatencyStats:
    """Recent successful calls per model and task. Used from the event loop only."""

    def __init__(self, rule: StallRule | None = None) -> None:
        self.rule = rule or StallRule()
        self._total: dict[Hashable, deque[int]] = {}
        self._first_chunk: dict[Hashable, deque[int]] = {}

    def observe(self, key: LatencyKey, latency_ms: int, first_chunk_ms: int | None) -> None:
        for k in (key, key.shared):
            self._push(self._total, k, latency_ms)
            if first_chunk_ms is not None:
                self._push(self._first_chunk, k, first_chunk_ms)

    def observe_record(self, record: UsageRecord) -> None:
        """A usage sink: only successful chat-model calls say how long a model takes."""
        if record.status != "ok" or record.section not in (None, "llm"):
            return
        key = LatencyKey(record.tenant_id, record.connection_name, record.model, record.task)
        self.observe(key, record.latency_ms, record.first_chunk_ms)

    def threshold(self, key: LatencyKey, *, streamed: bool, configured: float) -> float:
        store = self._first_chunk if streamed else self._total
        own = store.get(key, ())
        samples = own if len(own) >= self.rule.min_samples else store.get(key.shared, ())
        return stall_threshold(list(samples), configured, self.rule)

    def clear(self) -> None:
        self._total.clear()
        self._first_chunk.clear()

    def _push(self, store: dict[Hashable, deque[int]], key: Hashable, value: int) -> None:
        samples = store.get(key)
        if samples is None:
            samples = store[key] = deque(maxlen=self.rule.window)
        samples.append(value)


async def seed_latency_stats(
    session: AsyncSession, stats: LatencyStats, *, days: int = 7, limit: int = 20_000
) -> int:
    """Feed the last `days` of successful calls, oldest first; returns how many."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                LLMUsage.tenant_id,
                LLMUsage.connection_name,
                LLMUsage.model,
                LLMUsage.task,
                LLMUsage.latency_ms,
                LLMUsage.first_chunk_ms,
            )
            .where(
                LLMUsage.status == "ok",
                LLMUsage.created_at >= since,
                LLMUsage.section.is_(None) | (LLMUsage.section == "llm"),
            )
            .order_by(LLMUsage.created_at.desc(), LLMUsage.id.desc())
            .limit(limit)
        )
    ).all()
    for tenant_id, connection, model, task, latency_ms, first_chunk_ms in reversed(rows):
        stats.observe(LatencyKey(tenant_id, connection, model, task), latency_ms, first_chunk_ms)
    return len(rows)


_stats = LatencyStats()


def get_latency_stats() -> LatencyStats:
    return _stats
