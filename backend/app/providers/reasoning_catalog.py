"""Which thinking levels a chat model takes, and the vendor parameter each one sends
(ADR 0047 §1, task 91).

The `reasoning` param is one name across vendors; this module turns it into what the
model actually reads, from the connection and the model id alone:
- OpenAI-style reasoning models (o-series, gpt-5 and later): `reasoning_effort`, with
  the levels that model accepts (`gpt-6.1-sol` has no `none`, so no "off");
- Bailian and SiliconFlow's hybrid models (Qwen3, DeepSeek V3.1+, GLM-4.5+):
  `enable_thinking`, which is only on or off;
- models that always think (QwQ, `*-thinking`, DeepSeek R1), models that never do,
  Anthropic and DeepSeek's own API, and every model not recognized here: nothing, so a
  call never fails over a parameter the model doesn't take. Their only level is the
  vendor's default.

Like model_catalog, the rules read the model id and are a best-effort table: a model
they miss only loses the choice, and providers/llm.py retries once without the
parameter when a vendor still rejects it.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2

from app.providers.config import ProviderKind

logger = logging.getLogger(__name__)

# "on" is for the on/off models; low / medium / high for the effort ones.
ReasoningLevel = Literal["off", "on", "low", "medium", "high"]
REASONING_LEVELS: tuple[ReasoningLevel, ...] = ("off", "on", "low", "medium", "high")

Style = Literal["effort", "toggle"]

# OpenAI-compatible servers that switch thinking with `enable_thinking` and ignore
# `reasoning_effort` (Bailian's Qwen, SiliconFlow; checked 2026-10-16), by host suffix.
_TOGGLE_HOSTS = ("aliyuncs.com", "siliconflow.cn", "siliconflow.com")

_ALWAYS_THINKS = re.compile(r"qwq|thinking|-r1|reasoner", re.IGNORECASE)
# Hybrid models these hosts switch with `enable_thinking` (Bailian and SiliconFlow
# model docs, 2026-10). The fixed `-instruct` / `-thinking` variants are not hybrid.
_TOGGLE_MODELS = re.compile(
    r"^(qwen3|qwen-(plus|flash|turbo)|deepseek-v3\.[1-9]|glm-4\.[5-9]|glm-[5-9])",
    re.IGNORECASE,
)
_FIXED_VARIANT = re.compile(r"instruct|coder", re.IGNORECASE)

_EFFORT_ALL: tuple[ReasoningLevel, ...] = ("off", "low", "medium", "high")
_EFFORT_NO_OFF: tuple[ReasoningLevel, ...] = ("low", "medium", "high")
# First match wins. `reasoning_effort` values per model (OpenAI model pages; gpt-6-sol
# and gpt-6.1-sol probed through sub2api on 2026-10-16). Chat-tuned variants
# (`gpt-5-chat-latest`) don't reason and fall through to nothing.
_EFFORT_MODELS: tuple[tuple[re.Pattern[str], tuple[ReasoningLevel, ...]], ...] = (
    (re.compile(r"-chat|^o1-(mini|preview)"), ()),
    (re.compile(r"^gpt-6\.1"), _EFFORT_NO_OFF),
    (re.compile(r"^gpt-(5\.[1-9]|6)"), _EFFORT_ALL),
    # gpt-5's lowest level is `minimal`, which still thinks a little: not "off".
    (re.compile(r"^gpt-5"), _EFFORT_NO_OFF),
    (re.compile(r"^o[1-9]"), _EFFORT_NO_OFF),
)


@dataclass(frozen=True)
class ReasoningSpec:
    """The levels the settings page offers for a model (besides the default), and how
    they reach it. No levels: the model is left at its default."""

    style: Style | None = None
    levels: tuple[ReasoningLevel, ...] = ()

    def kwargs(self, level: str | None) -> dict[str, Any]:
        """The vendor's parameter for `level`; nothing for a level this model doesn't
        take. Low / medium / high saved before task 91 mean "on" to an on/off model."""
        if level is None or not self.levels:
            return {}
        if self.style == "toggle":
            return {"extra_body": {"enable_thinking": level != "off"}}
        if level not in self.levels:
            return {}
        return {"reasoning_effort": "none" if level == "off" else level}


_NONE = ReasoningSpec()


def reasoning_spec(kind: ProviderKind | str, base_url: str, model: str) -> ReasoningSpec:
    if kind not in ("openai", "openai_compatible"):
        return _NONE
    # SiliconFlow and relays prefix the vendor: "Qwen/Qwen3-8B", "openai/gpt-5".
    name = model.rsplit("/", 1)[-1].lower()
    if _ALWAYS_THINKS.search(name):
        return _NONE
    host = (urlsplit(base_url).hostname or "").lower()
    if host.endswith(_TOGGLE_HOSTS):
        if _TOGGLE_MODELS.search(name) and not _FIXED_VARIANT.search(name):
            return ReasoningSpec("toggle", ("off", "on"))
        return _NONE
    for pattern, levels in _EFFORT_MODELS:
        if pattern.search(name):
            return ReasoningSpec("effort", levels) if levels else _NONE
    return _NONE


# The parameters ReasoningSpec.kwargs puts in a request body.
_SENT_FIELDS = ("reasoning_effort", "enable_thinking")
# What a vendor's 400 says when it is the thinking parameter it refuses ("Unsupported
# value: 'none' ... reasoning_effort", "enable_thinking is not supported ...").
_REFUSES_REASONING = re.compile(r"reasoning|thinking", re.IGNORECASE)


class WithoutReasoningRetry(httpx2.AsyncBaseTransport):
    """The safety net under the table above: when a vendor answers 400 about the
    thinking parameter, the same request goes once more without it. Any other 400,
    or the second answer, goes back as it is."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code != 400:
            return response
        body = _json_body(request)
        if body is None or not any(f in body for f in _SENT_FIELDS):
            return response
        await response.aread()
        if not _REFUSES_REASONING.search(response.text):
            return response
        logger.warning(
            "%s refused the thinking parameter for %r; retrying without it",
            request.url.host,
            body.get("model"),
        )
        await response.aclose()
        for field in _SENT_FIELDS:
            body.pop(field, None)
        headers = request.headers.copy()
        del headers["content-length"]
        retry = httpx2.Request(
            request.method,
            request.url,
            headers=headers,
            content=json.dumps(body).encode(),
            extensions=request.extensions,
        )
        return await self._inner.handle_async_request(retry)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _json_body(request: httpx2.Request) -> dict[str, Any] | None:
    try:
        body = json.loads(request.content)
    except (httpx2.RequestNotRead, ValueError):
        return None
    return body if isinstance(body, dict) else None
