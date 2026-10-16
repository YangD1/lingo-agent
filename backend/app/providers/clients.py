"""Chat model subclasses: the guarded HTTP client (ADR 0004 §4) and streamed usage
(task 93)."""

from collections.abc import AsyncIterator, Mapping
from functools import cached_property
from typing import Any, cast

import anthropic
import httpx2
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessageChunk
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr


class GuardedChatAnthropic(ChatAnthropic):
    """ChatAnthropic has no `http_async_client` field: it builds its httpx client inside
    the private cached properties below, so we override them. Depends on
    langchain-anthropic internals; tests/unit/test_net_guard.py fails if they change."""

    _guarded_http_client: httpx2.AsyncClient | None = PrivateAttr(default=None)

    def with_http_client(self, client: httpx2.AsyncClient) -> "GuardedChatAnthropic":
        self._guarded_http_client = client
        return self

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        if self._guarded_http_client is None:
            raise RuntimeError("GuardedChatAnthropic used without with_http_client()")
        params: dict[str, Any] = {**self._client_params, "http_client": self._guarded_http_client}
        return anthropic.AsyncClient(**params)

    @cached_property
    def _client(self) -> anthropic.Client:
        raise RuntimeError("sync model calls are disabled; use the async API (ainvoke/astream)")


class UsageOnceChatOpenAI(ChatOpenAI):
    """Reports a streamed call's token usage once, at the end (task 93).

    langchain adds up the usage on every chunk, which is right for OpenAI (only the
    last chunk carries it) but some OpenAI-compatible servers (SiliconFlow) put the
    running total on every chunk: a 17k-token answer was billed as 141M. Each field
    keeps its largest value instead, which is the total in both cases and also when
    input and output come in separate chunks. core passes chunks from `_astream` on to
    callbacks and the final message, so this is the one place to fix it.
    """

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        usage: UsageMetadata | None = None
        async for chunk in super()._astream(*args, **kwargs):
            message = chunk.message
            if isinstance(message, AIMessageChunk) and message.usage_metadata:
                usage = cast(UsageMetadata, _largest(usage or {}, message.usage_metadata))
                chunk = ChatGenerationChunk(
                    message=message.model_copy(update={"usage_metadata": None}),
                    generation_info=chunk.generation_info,
                )
            yield chunk
        if usage is not None:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


def _largest(seen: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(seen)
    for key, value in new.items():
        old = merged.get(key)
        merged[key] = (
            _largest(old or {}, value) if isinstance(value, Mapping) else max(value, old or 0)
        )
    return merged
