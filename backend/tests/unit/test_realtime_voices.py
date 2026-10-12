"""Call voices a learner may pick, by vendor and model (ADR 0032 §3, Q66k)."""

from app.providers.config import ConnectionSpec, ResolvedModel
from app.providers.realtime import realtime_vendor
from app.providers.realtime_voices import default_realtime_voice, realtime_voice_options
from tests.unit.provider_fixtures import conn


def _model(spec: ConnectionSpec, model: str) -> ResolvedModel:
    return ResolvedModel(spec.name, spec.kind, model, spec.base_url, None, params=spec.params)


def _ids(model: ResolvedModel) -> list[str]:
    return [v.id for v in realtime_voice_options(model)]


def test_openai_voices_and_default() -> None:
    openai = conn("openai", base_url="https://api.openai.com/v1")
    model = _model(openai, "gpt-realtime-2.1")
    assert realtime_vendor(model) == "openai"
    assert _ids(model)[:2] == ["marin", "cedar"] and len(_ids(model)) == 10
    assert default_realtime_voice(model) == "marin"


def test_qwen_voices_follow_the_model_generation() -> None:
    qwen = conn("qwen", "openai_compatible", base_url="https://dashscope.aliyuncs.com/v1")
    older = _model(qwen, "qwen3-omni-flash-realtime")
    newer = _model(qwen, "qwen3.8-omni-flash-realtime")
    assert _ids(older)[0] == "Cherry" and "Tina" not in _ids(older)
    assert _ids(newer)[0] == "Tina" and "Mione" in _ids(newer)
    # Qwen's default is the vendor's own: nothing is sent, the first is listed.
    assert default_realtime_voice(newer) == "Tina"
    # A workspace host is still Qwen.
    workspace = conn(
        "ws",
        "openai_compatible",
        base_url="https://dashscope.aliyuncs.com/v1",
        realtime_url="wss://abc.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
    )
    assert _ids(_model(workspace, "qwen3.5-omni-flash-realtime"))[0] == "Tina"


def test_no_catalog_where_no_official_list() -> None:
    stepfun = conn("stepfun", "openai_compatible", base_url="https://api.stepfun.com/v1")
    assert _ids(_model(stepfun, "step-audio-2"))[0] == "qingchunshaonv"
    assert _ids(_model(stepfun, "stepaudio-2.5-realtime")) == []
    relay = conn("relay", "openai", base_url="https://relay.example.com/v1")
    assert realtime_vendor(_model(relay, "gpt-realtime-2.1")) is None
    assert _ids(_model(relay, "gpt-realtime-2.1")) == []
