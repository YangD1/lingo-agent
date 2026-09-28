"""SDK client subclasses needed to inject the guarded HTTP client (ADR 0004 §4)."""

from functools import cached_property
from typing import Any

import anthropic
import httpx2
from langchain_anthropic import ChatAnthropic
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
