import json
from typing import Any

import httpx2
import openai
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.providers.config import ResolvedModel
from app.providers.llm import build_chat_model
from app.providers.reasoning_catalog import ReasoningSpec, WithoutReasoningRetry, reasoning_spec

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
        ("openai_compatible", SILICONFLOW, "deepseek-ai/DeepSeek-V4-Flash", ("off", "on")),
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
    assert reasoning_spec(kind, base_url, model).levels == levels


def test_a_model_without_levels_sends_nothing() -> None:
    assert ReasoningSpec().kwargs("off") == {}
    assert reasoning_spec("openai_compatible", RELAY, "gpt-4o").kwargs("high") == {}


def test_effort_levels_the_model_lacks_send_nothing() -> None:
    spec = reasoning_spec("openai_compatible", RELAY, "gpt-6.1-sol")
    assert spec.kwargs("off") == {}
    assert spec.kwargs("on") == {}
    assert spec.kwargs("medium") == {"reasoning_effort": "medium"}


# --- retry without the thinking parameter (task 91.3) ----------------------------------

COMPLETION = {
    "id": "c",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-6.1-sol",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }
    ],
}
REFUSED = {
    "error": {
        "message": "Unsupported value: 'none' is not supported with this model. "
        "Supported values are: 'low', 'medium', 'high'.",
        "param": "reasoning_effort",
    }
}


def vendor(refusal: dict[str, Any], seen: list[dict[str, Any]]) -> httpx2.MockTransport:
    """Refuses any request carrying a thinking parameter with `refusal`."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning_effort" in body or "enable_thinking" in body:
            return httpx2.Response(400, json=refusal)
        return httpx2.Response(200, json=COMPLETION)

    return httpx2.MockTransport(handle)


def chat(transport: httpx2.AsyncBaseTransport, **kwargs: Any) -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-6.1-sol",
        api_key=SecretStr("sk-test"),
        base_url=RELAY,
        max_retries=0,
        http_async_client=httpx2.AsyncClient(transport=WithoutReasoningRetry(transport)),
        **kwargs,
    )


async def test_a_refused_thinking_parameter_is_dropped_once() -> None:
    seen: list[dict[str, Any]] = []
    reply = await chat(vendor(REFUSED, seen), reasoning_effort="none").ainvoke("hi")
    assert reply.content == "hi"
    assert [("reasoning_effort" in b) for b in seen] == [True, False]
    toggle: list[dict[str, Any]] = []
    refused = {"error": {"message": "enable_thinking is not supported by this model"}}
    model = chat(vendor(refused, toggle), extra_body={"enable_thinking": True})
    assert (await model.ainvoke("hi")).content == "hi"
    assert [("enable_thinking" in b) for b in toggle] == [True, False]


async def test_other_refusals_are_not_retried() -> None:
    seen: list[dict[str, Any]] = []
    other = {"error": {"message": "context length exceeded"}}
    with pytest.raises(openai.BadRequestError, match="context length"):
        await chat(vendor(other, seen), reasoning_effort="low").ainvoke("hi")
    assert len(seen) == 1


def test_only_models_sent_a_thinking_parameter_get_the_retry() -> None:
    def transport(model: str) -> object:
        resolved = ResolvedModel(
            "relay", "openai_compatible", model, RELAY, None, {"reasoning": "low"}
        )
        built = build_chat_model(resolved, "chat")
        assert isinstance(built, ChatOpenAI)
        return built.http_async_client._transport  # type: ignore[union-attr]

    assert isinstance(transport("gpt-6-sol"), WithoutReasoningRetry)
    assert not isinstance(transport("gpt-4o"), WithoutReasoningRetry)
