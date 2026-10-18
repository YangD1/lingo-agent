"""One article's model calls share a retry budget (task 103.0, ADR 0056): the critic's
route is resilient, which leaves it no SDK retries, so without the budget a failed
critique dropped every question."""

import pytest

from app.providers import resilience
from app.providers.llm import RoutedModel
from app.services.reading import worker
from tests.unit.test_resilience import (
    CTX,
    EXPECTED,
    Items,
    _isolated,
    breaker,
    routed,
    scripted,
)

__all__ = ["_isolated", "breaker"]


def chains(monkeypatch: pytest.MonkeyPatch, **by_task: RoutedModel) -> None:
    monkeypatch.setattr(resilience, "get_routed_models", lambda ctx, task: (by_task[task],))


async def test_a_failed_critique_is_sent_again(monkeypatch: pytest.MonkeyPatch) -> None:
    critic = routed("c", "500", "ok", records=[])
    chains(monkeypatch, exercise_critic=critic)
    _, _, critique = worker.model_calls(CTX, {})

    reply = await critique(["q"], Items)

    assert reply.output == EXPECTED
    assert scripted(critic).calls == ["500", "ok"]


async def test_the_calls_share_one_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "ARTICLE_RETRIES", 1)
    rewrite = routed("r", "500", "ok", records=[])
    critic = routed("c", "500", "ok", records=[])
    chains(monkeypatch, article_rewrite=rewrite, exercise_critic=critic)
    rewriting, _, critique = worker.model_calls(CTX, {})

    assert (await rewriting(["q"], Items)).output == EXPECTED
    with pytest.raises(Exception, match="500"):
        await critique(["q"], Items)
    assert scripted(critic).calls == ["500"]
