from datetime import date

import pytest

from app.usage.dashboard import Price, UsageRow, build_dashboard, cost_of

DAY = date(2026, 10, 13)


def row(**overrides: object) -> UsageRow:
    fields: dict[str, object] = {
        "day": DAY,
        "member": None,
        "connection": "openai",
        "model": "gpt-5-mini",
        "task": "chat",
        "background": False,
        "calls": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "characters": 0,
        "audio_minutes": 0.0,
        "errors": 0,
        "fallbacks": 0,
        "retries": 0,
        "stalls": 0,
        "cancels": 0,
    }
    fields.update(overrides)
    return UsageRow(**fields)  # type: ignore[arg-type]


def test_cost_adds_each_priced_part() -> None:
    price = Price(input_per_mtok=2, output_per_mtok=8, per_kchar=0.5, per_minute=0.1)
    cost = cost_of(
        price, input_tokens=500_000, output_tokens=250_000, characters=2_000, audio_minutes=30
    )
    assert cost is not None
    assert cost.amount == pytest.approx(1 + 2 + 1 + 3)
    assert not cost.partial


def test_cost_without_a_price_is_none() -> None:
    kwargs = {"input_tokens": 10, "output_tokens": 0, "characters": 0, "audio_minutes": 0.0}
    assert cost_of(None, **kwargs) is None  # type: ignore[arg-type]
    assert cost_of(Price(), **kwargs) is None  # type: ignore[arg-type]


def test_usage_without_its_price_makes_the_cost_partial() -> None:
    cost = cost_of(
        Price(input_per_mtok=2),
        input_tokens=1_000_000,
        output_tokens=10,
        characters=0,
        audio_minutes=0,
    )
    assert cost is not None
    assert cost.amount == pytest.approx(2)
    assert cost.partial
    # A missing price for something not used is fine.
    cost = cost_of(
        Price(input_per_mtok=2),
        input_tokens=1_000_000,
        output_tokens=0,
        characters=0,
        audio_minutes=0,
    )
    assert cost is not None and not cost.partial


def test_every_day_in_range_gets_an_entry() -> None:
    board = build_dashboard([row(day=date(2026, 10, 12))], {}, date(2026, 10, 11), DAY)
    assert [(d.day.day, d.tally.calls) for d in board.days] == [(11, 0), (12, 1), (13, 0)]


def test_groups_sum_and_sort_by_calls() -> None:
    board = build_dashboard(
        [
            row(task="reflect", background=True, calls=3, errors=1, retries=2, stalls=1),
            row(task="chat", calls=2, fallbacks=1),
            row(task="chat", model="deepseek-chat", connection="deepseek", calls=4),
            row(task="tts", member="Alex", calls=5, input_tokens=0, characters=900),
        ],
        {},
        DAY,
        DAY,
    )
    assert board.total.calls == 14
    assert (board.total.errors, board.total.fallbacks, board.total.characters) == (1, 1, 900)
    assert (board.total.retries, board.total.stalls, board.total.cancels) == (2, 1, 0)
    assert [(t.task, t.background, t.tally.calls) for t in board.tasks] == [
        ("chat", False, 6),
        ("tts", False, 5),
        ("reflect", True, 3),
    ]
    assert [(m.model, m.tally.calls) for m in board.models] == [
        ("gpt-5-mini", 10),
        ("deepseek-chat", 4),
    ]
    # The account's own calls first, even with fewer.
    assert [(m.member, m.tally.calls) for m in board.members] == [(None, 9), ("Alex", 5)]


def test_costs_come_only_from_priced_models() -> None:
    prices = {("openai", "gpt-5-mini"): Price(input_per_mtok=2)}
    board = build_dashboard(
        [row(), row(connection="deepseek", model="deepseek-chat")], prices, DAY, DAY
    )
    assert board.priced
    assert board.total.cost == pytest.approx(2)
    # deepseek used tokens with no price: the total leaves it out.
    assert board.total.cost_partial
    by_model = {m.model: m.tally for m in board.models}
    assert by_model["gpt-5-mini"].cost == pytest.approx(2)
    assert not by_model["gpt-5-mini"].cost_partial
    assert by_model["deepseek-chat"].cost is None


def test_nothing_priced_shows_no_cost() -> None:
    board = build_dashboard([row()], {}, DAY, DAY)
    assert not board.priced
    assert board.total.cost is None
