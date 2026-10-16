import pytest

from app.providers.reasoning_catalog import ReasoningSpec, reasoning_spec

RELAY = "https://relay.example.com/v1"
BAILIAN = "https://dashscope.aliyuncs.com/compatible-mode/v1"
SILICONFLOW = "https://api.siliconflow.cn/v1"


@pytest.mark.parametrize(
    ("kind", "base_url", "model", "levels"),
    [
        ("openai_compatible", RELAY, "gpt-6-sol", ("off", "low", "medium", "high")),
        ("openai_compatible", RELAY, "gpt-6.1-sol", ("low", "medium", "high")),
        ("openai", "https://api.openai.com/v1", "gpt-5.1", ("off", "low", "medium", "high")),
        ("openai", "https://api.openai.com/v1", "gpt-5-mini", ("low", "medium", "high")),
        ("openai", "https://api.openai.com/v1", "o4-mini", ("low", "medium", "high")),
        ("openai_compatible", RELAY, "openai/gpt-5.2", ("off", "low", "medium", "high")),
        ("openai", "https://api.openai.com/v1", "gpt-5-chat-latest", ()),
        ("openai", "https://api.openai.com/v1", "o1-mini", ()),
        ("openai", "https://api.openai.com/v1", "gpt-4o", ()),
        ("openai_compatible", BAILIAN, "qwen-plus", ("off", "on")),
        ("openai_compatible", BAILIAN, "qwen3-235b-a22b", ("off", "on")),
        ("openai_compatible", BAILIAN, "deepseek-v3.2", ("off", "on")),
        ("openai_compatible", SILICONFLOW, "Qwen/Qwen3-8B", ("off", "on")),
        ("openai_compatible", SILICONFLOW, "zai-org/GLM-4.6", ("off", "on")),
        # Always thinks, never thinks, or a fixed variant: left at the default.
        ("openai_compatible", BAILIAN, "qwq-plus", ()),
        ("openai_compatible", BAILIAN, "qwen3-235b-a22b-thinking-2507", ()),
        ("openai_compatible", BAILIAN, "qwen3-235b-a22b-instruct-2507", ()),
        ("openai_compatible", BAILIAN, "qwen-max", ()),
        ("openai_compatible", SILICONFLOW, "deepseek-ai/DeepSeek-R1", ()),
        # On the on/off hosts only their hybrid models count.
        ("openai_compatible", BAILIAN, "gpt-6-sol", ()),
        ("openai_compatible", "http://localhost:11434/v1", "llama3.1", ()),
        ("anthropic", "https://api.anthropic.com", "claude-opus-5-5", ()),
        ("deepseek", "https://api.deepseek.com/v1", "deepseek-chat", ()),
    ],
)
def test_levels_follow_the_model(
    kind: str, base_url: str, model: str, levels: tuple[str, ...]
) -> None:
    assert reasoning_spec(kind, base_url, model).levels == levels  # type: ignore[arg-type]


def test_a_model_without_levels_sends_nothing() -> None:
    assert ReasoningSpec().kwargs("off") == {}
    assert reasoning_spec("openai_compatible", RELAY, "gpt-4o").kwargs("high") == {}


def test_effort_levels_the_model_lacks_send_nothing() -> None:
    spec = reasoning_spec("openai_compatible", RELAY, "gpt-6.1-sol")
    assert spec.kwargs("off") == {}
    assert spec.kwargs("on") == {}
    assert spec.kwargs("medium") == {"reasoning_effort": "medium"}
