"""The tutor opens the workspace by itself, and the learner turns that off in words
(ADR 0045)."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.prompts import load_prompt
from app.providers import llm
from app.providers.config import ResolvedModel
from tests.integration.test_chat_tools import (
    Script,
    ToolFake,
    _clear_caches,  # noqa: F401
    ready,
    send,
)
from tests.integration.test_workspace_tools import system


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    shared = Script()

    def build(resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None) -> Any:
        return ToolFake(script=shared, callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)
    return shared


async def test_the_prompt_follows_the_setting(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = ["Hi.", "Hi again."]

    await send(client, conversation, "Hello")
    first = system(script, 0)
    assert "### The workspace" in first and "{workspace_rule}" not in first
    assert load_prompt("tutor_workspace_auto") in first

    assert (await client.put("/tutor", json={"workspace_auto_open": False})).status_code == 200
    await send(client, conversation, "Hello again")
    second = system(script, 1)
    assert load_prompt("tutor_workspace_on_request") in second
    assert load_prompt("tutor_workspace_auto") not in second
