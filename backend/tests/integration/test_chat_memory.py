"""The tutor sees the learner's memories through the real send-message endpoint."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantMember, User
from app.memory import service
from app.providers import llm
from app.providers.config import ResolvedModel
from tests.integration.test_chat_send import connect, login, new_conversation, send


class PromptRecorder(BaseChatModel):
    prompts: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "prompt-recorder"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("the chat graph always streams")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.prompts.append(str(messages[0].content))
        yield ChatGenerationChunk(message=AIMessageChunk(content="Sure!"))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> PromptRecorder:
    model = PromptRecorder()

    def build(
        resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None
    ) -> BaseChatModel:
        return model

    monkeypatch.setattr(llm, "build_chat_model", build)
    return model


async def test_new_conversation_uses_memories_and_forgets_deleted_ones(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    await login(client)
    await connect(client, "deepseek")  # no embedding model: retrieval by recency
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    tenant_id = await db_session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    await service.update_profile(
        db_session, user.id, {"occupation": "backend developer"}, by_learner=True
    )
    fact = await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user.id,
        kind="fact",
        content="Has a job interview next month",
    )

    status, events, _ = await send(client, await new_conversation(client), "Help me practise")
    assert status == 200 and events[-1][0] == "done"
    assert "Occupation: backend developer" in recorder.prompts[-1]
    assert "Has a job interview next month" in recorder.prompts[-1]

    await service.delete_memory(db_session, user.id, fact.id)
    await send(client, await new_conversation(client), "Help me practise")
    assert "job interview" not in recorder.prompts[-1]


async def test_other_learners_memories_never_leak(
    client: AsyncClient, db_session: AsyncSession, recorder: PromptRecorder
) -> None:
    await login(client, "other@example.com")
    other = await db_session.scalar(select(User).where(User.email == "other@example.com"))
    assert other is not None
    other_tenant = await db_session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == other.id)
    )
    assert other_tenant is not None
    await service.add_memory(
        db_session, tenant_id=other_tenant, user_id=other.id, kind="fact", content="Secret hobby"
    )
    await client.post("/auth/logout")

    await login(client)
    await connect(client, "deepseek")
    await send(client, await new_conversation(client), "Hello")
    assert "Secret hobby" not in recorder.prompts[-1]
    assert "About this learner" not in recorder.prompts[-1]
