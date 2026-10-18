import uuid

import pytest

from app.providers.latency import LatencyKey, LatencyStats, StallRule, p95, stall_threshold
from app.usage.recorder import UsageRecord

KEY = LatencyKey(uuid.UUID(int=1), "sub2api", "gpt-6.1", "exercise_critic")
RULE = StallRule(factor=3, floor=20, ceiling=120, min_samples=20, window=200)


def record(**overrides: object) -> UsageRecord:
    fields: dict[str, object] = {
        "tenant_id": KEY.tenant_id,
        "user_id": None,
        "conversation_id": None,
        "task": KEY.task,
        "connection_name": KEY.connection,
        "model": KEY.model,
        "input_tokens": 10,
        "output_tokens": 5,
        "latency_ms": 6000,
        "status": "ok",
        "is_fallback": False,
        "error_code": None,
        "section": "llm",
        "first_chunk_ms": 1500,
    }
    fields.update(overrides)
    return UsageRecord(**fields)  # type: ignore[arg-type]


def test_p95_is_nearest_rank() -> None:
    assert p95(list(range(1, 101))) == 95
    assert p95([7]) == 7
    assert p95([3, 1, 2]) == 3


def test_a_fast_model_is_found_stalled_early() -> None:
    # sub2api's critic: ~6 s, slowest normal 17 s (task 100.9).
    samples = [6000] * 18 + [12_000, 17_000]
    assert stall_threshold(samples, 120, RULE) == pytest.approx(36.0)


def test_never_below_the_floor() -> None:
    assert stall_threshold([1000] * 20, 120, RULE) == 20


def test_a_slow_model_is_capped_at_the_ceiling() -> None:
    # DeepSeek thinking critic: p95 133 s (task 101.1) - no worse than the old timeout.
    assert stall_threshold([133_000] * 20, 120, RULE) == 120


def test_a_longer_configured_timeout_raises_the_ceiling() -> None:
    assert stall_threshold([133_000] * 20, 300, RULE) == 300
    assert stall_threshold([60_000] * 20, 300, RULE) == 180


def test_too_few_samples_use_the_configured_timeout() -> None:
    assert stall_threshold([6000] * 19, 120, RULE) == 120
    assert stall_threshold([], 45, RULE) == 45


def test_streamed_calls_use_the_first_chunk_times() -> None:
    stats = LatencyStats(RULE)
    for _ in range(20):
        stats.observe(KEY, 30_000, 2_000)
    assert stats.threshold(KEY, streamed=False, configured=120) == 90
    assert stats.threshold(KEY, streamed=True, configured=120) == 20


def test_other_keys_have_their_own_samples() -> None:
    stats = LatencyStats(RULE)
    for _ in range(20):
        stats.observe(KEY, 6000, None)
    other = KEY._replace(model="deepseek-v4.1")
    assert stats.threshold(other, streamed=False, configured=120) == 120
    # Not streamed: no first-chunk samples.
    assert stats.threshold(KEY, streamed=True, configured=120) == 120


def test_only_the_last_window_counts() -> None:
    stats = LatencyStats(StallRule(min_samples=2, window=3))
    for ms in (100_000, 100_000, 10_000, 10_000, 10_000):
        stats.observe(KEY, ms, None)
    assert stats.threshold(KEY, streamed=False, configured=120) == 30


@pytest.mark.parametrize(
    "overrides",
    [{"status": "error"}, {"status": "stalled"}, {"status": "cancelled"}, {"section": "tts"}],
)
def test_only_successful_chat_calls_are_observed(overrides: dict[str, object]) -> None:
    stats = LatencyStats(StallRule(min_samples=1))
    stats.observe_record(record(**overrides))
    assert stats.threshold(KEY, streamed=False, configured=120) == 120


def test_usage_records_feed_the_stats() -> None:
    stats = LatencyStats(StallRule(min_samples=1))
    stats.observe_record(record())
    assert stats.threshold(KEY, streamed=False, configured=120) == 20
    assert stats.threshold(KEY, streamed=True, configured=120) == 20
    stats.observe_record(record(latency_ms=50_000, first_chunk_ms=None))
    assert stats.threshold(KEY, streamed=False, configured=120) == 120
