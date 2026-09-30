from pathlib import Path

import pytest

from app.providers.config import RouteSpec
from app.usage.estimates import TaskHistory, current_model, estimate_call
from app.usage.features import FeatureCall, FeaturesError, get_features, load_features
from tests.unit.provider_fixtures import conn, make_config, make_ctx


def call(**overrides: object) -> FeatureCall:
    fields: dict[str, object] = {
        "task": "chat",
        "timing": "now",
        "default": {"input_tokens": 100, "output_tokens": 20},
    }
    fields.update(overrides)
    return FeatureCall.model_validate(fields)


# --- catalog ------------------------------------------------------------------------------


def test_shipped_catalog_loads() -> None:
    catalog = get_features()
    assert {"chat_message", "chat_image", "chat_audio", "practice_start", "advice"} <= set(
        catalog.features
    )
    chat = catalog.features["chat_message"].calls
    assert [(c.task, c.timing) for c in chat] == [
        ("chat", "now"),
        ("chat_tools", "now"),
        ("reflect", "background"),
        ("memory", "background"),
    ]
    # Openings are served by the chat model but recorded under their own task.
    (opening,) = catalog.features["practice_start"].calls
    assert (opening.task, opening.route_task) == ("practice_opening", "chat")


def test_every_shipped_asr_call_is_estimated_by_audio_length() -> None:
    for feature in get_features().features.values():
        for c in feature.calls:
            assert (c.section == "asr") == (c.default.audio_seconds is not None)


def test_asr_calls_need_audio_seconds() -> None:
    with pytest.raises(ValueError, match="audio_seconds"):
        call(task="asr", section="asr")
    with pytest.raises(ValueError, match="audio_seconds"):
        call(default={"audio_seconds": 10})


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "features.yaml"
    path.write_text(
        "window: 5\nfeatures:\n  x:\n    calls:\n"
        "      - {task: chat, timing: now, default: {}, cost: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(FeaturesError, match="cost"):
        load_features(path)


def test_missing_catalog_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FeaturesError, match="not found"):
        load_features(tmp_path / "nope.yaml")


# --- estimates ----------------------------------------------------------------------------


def test_without_history_the_default_is_used() -> None:
    for history in (
        None,
        TaskHistory(samples=0, input_tokens=0, output_tokens=0, audio_seconds=None),
    ):
        estimate = estimate_call(call(), history, "openai:gpt-5-mini")
        assert (estimate.source, estimate.samples) == ("default", 0)
        assert (estimate.input_tokens, estimate.output_tokens) == (100, 20)
        assert estimate.model == "openai:gpt-5-mini"


def test_history_replaces_the_default() -> None:
    history = TaskHistory(samples=7, input_tokens=2300, output_tokens=410, audio_seconds=None)
    estimate = estimate_call(call(per="image"), history, None)
    assert (estimate.source, estimate.samples, estimate.per) == ("history", 7, "image")
    assert (estimate.input_tokens, estimate.output_tokens) == (2300, 410)
    assert estimate.model is None


def test_current_model_is_the_first_usable_one_in_the_route() -> None:
    config = make_config()
    ctx = make_ctx(conn("deepseek"), conn("openai"))
    assert current_model(config, ctx, call()) == "openai:gpt-5-mini"  # chat route
    assert current_model(config, ctx, call(task="advice")) == "deepseek:deepseek-chat"
    # Recorded as practice_opening, routed as chat.
    assert current_model(config, ctx, call(task="practice_opening", route="chat")) == (
        "openai:gpt-5-mini"
    )
    overridden = make_ctx(
        conn("deepseek"),
        routes={("llm", "advice"): RouteSpec(models=["deepseek:deepseek-reasoner"])},
    )
    assert current_model(config, overridden, call(task="advice")) == "deepseek:deepseek-reasoner"


def test_current_model_is_none_when_nothing_is_configured() -> None:
    config = make_config()  # no asr section, no vision route
    ctx = make_ctx(conn("openai"))
    asr = call(task="asr", section="asr", default={"audio_seconds": 10})
    assert current_model(config, ctx, asr) is None
    assert current_model(config, ctx, call(task="vision")) is None
    assert current_model(config, make_ctx(), call()) is None
