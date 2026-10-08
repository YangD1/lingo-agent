"""Running one diagnosis: checks, the call, the row and the memory (task 46.3, Q46d)."""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.diagnosis.checks import DiagnosisOut, RootCauseOut
from app.adaptive.diagnosis.service import Outcome, Trigger, run_diagnosis
from app.adaptive.graph_sync import sync_kc_edges
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import ModelReply, StructuredCall
from app.db.models import Diagnosis, KCEvidence, Memory, Tenant, UserProfile
from app.memory.service import delete_memory
from app.scheduler import prefs
from tests.integration.test_diagnosis_context import CATALOG, NOW, _mistakes
from tests.integration.test_word_examples_prefetch import learner

RULES = get_rules()


class FakeCalls:
    """Stands in for `structured_call`: one cause on the target's own mistakes, or the
    given causes."""

    def __init__(self, causes: list[dict[str, Any]] | None = None) -> None:
        self.causes = causes
        self.calls: list[tuple[Any, str, str]] = []

    def __call__(self, ctx: Any, config: Any, task: str) -> StructuredCall:
        async def call(messages: Sequence[Any], schema: type[Any]) -> ModelReply:
            prompt = str(messages[-1].content)
            self.calls.append((config, task, prompt))
            if self.causes is not None:
                causes = self.causes
            else:
                ids = [
                    int(line.split()[2]) for line in prompt.splitlines() if "- evidence " in line
                ]
                causes = [
                    {
                        "hypothesis": f"Cause {len(self.calls)}.",
                        "kc_ids": ["g.one"],
                        "evidence_ids": ids,
                        "confidence": "high",
                        "suggestion": "Practise it.",
                    }
                ]
            out = DiagnosisOut(root_causes=[RootCauseOut.model_validate(c) for c in causes])
            return ModelReply(out, "conn:model")

        return call


async def _setup(client: AsyncClient, session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A learner with three counted mistakes on g.one (a prerequisite: g.base)."""
    await sync_kc_edges(session, CATALOG)
    user_id, tenant_id = await learner(client, session, model=False)
    session.add_all(_mistakes(user_id, "g.one", 3))
    await session.commit()
    return user_id, tenant_id


async def _run(
    app: FastAPI,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    calls: FakeCalls,
    trigger: Trigger = "weekly",
    *,
    hours: int = 0,
) -> Outcome:
    return await run_diagnosis(
        app.state.sessionmaker,
        user_id,
        tenant_id,
        trigger,
        rules=RULES,
        catalog=CATALOG,
        now=NOW + timedelta(hours=hours),
        calls=calls,
    )


async def _diagnoses(session: AsyncSession, user_id: uuid.UUID) -> list[Diagnosis]:
    session.expire_all()
    return list(
        await session.scalars(
            select(Diagnosis).where(Diagnosis.user_id == user_id).order_by(Diagnosis.created_at)
        )
    )


async def _facts(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    session.expire_all()
    return list(
        await session.scalars(
            select(Memory.content).where(Memory.user_id == user_id, Memory.kind == "fact")
        )
    )


async def test_a_diagnosis_is_stored_with_its_memory(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await _setup(client, db_session)
    calls = FakeCalls()

    outcome = await _run(app, user_id, tenant_id, calls, "after_set")

    [row] = await _diagnoses(db_session, user_id)
    assert outcome == Outcome(diagnosis_id=row.id)
    config, task, prompt = calls.calls[0]
    assert task == "diagnose"
    assert config["metadata"] == {"user_id": str(user_id), "background": True}
    assert prompt.startswith("Write in: Simplified Chinese")
    newest = await db_session.scalar(
        select(KCEvidence.id).where(KCEvidence.user_id == user_id).order_by(KCEvidence.id.desc())
    )
    assert (row.trigger, row.target_kc_ids, row.language, row.model) == (
        "after_set",
        ["g.one"],
        "zh",
        "conn:model",
    )
    assert (row.evidence_upto, row.rules_version) == (newest, RULES.version)
    assert [c["hypothesis"] for c in row.root_causes] == ["Cause 1."]
    assert len(row.root_causes[0]["evidence_ids"]) == 3
    assert row.memory_id is not None
    assert await _facts(db_session, user_id) == ["私教的诊断：Cause 1."]  # noqa: RUF001


async def test_the_memory_is_updated_in_place_and_written_again_once_deleted(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await _setup(client, db_session)
    db_session.add(UserProfile(user_id=user_id, explanation_language="en"))
    await db_session.commit()
    calls = FakeCalls()

    await _run(app, user_id, tenant_id, calls)
    await _run(app, user_id, tenant_id, calls, hours=1)
    first, second = await _diagnoses(db_session, user_id)
    memory_id = second.memory_id
    assert memory_id is not None and first.memory_id == memory_id
    assert await _facts(db_session, user_id) == ["Tutor's diagnosis: Cause 2."]

    await delete_memory(db_session, user_id, memory_id)
    await _run(app, user_id, tenant_id, calls, hours=2)
    rows = await _diagnoses(db_session, user_id)
    assert [r.memory_id for r in rows[:2]] == [None, None]
    assert rows[2].memory_id is not None
    assert await _facts(db_session, user_id) == ["Tutor's diagnosis: Cause 3."]


async def test_without_a_cause_that_holds_the_memory_is_left_alone(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await _setup(client, db_session)
    await _run(app, user_id, tenant_id, FakeCalls())
    made_up = {
        "hypothesis": "A guess.",
        "kc_ids": ["g.one"],
        "evidence_ids": [999_999, 999_998],
        "confidence": "low",
        "suggestion": "",
    }

    outcome = await _run(app, user_id, tenant_id, FakeCalls([made_up]), hours=1)

    rows = await _diagnoses(db_session, user_id)
    assert outcome.diagnosis_id == rows[1].id
    assert (rows[1].root_causes, rows[1].memory_id) == ([], None)
    assert await _facts(db_session, user_id) == ["私教的诊断：Cause 1."]  # noqa: RUF001


async def test_skipped_without_a_call(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await _setup(client, db_session)
    other, other_tenant = await learner(client, db_session, model=False)
    calls = FakeCalls()

    # Fewer mistakes than min_mistakes.
    assert await _run(app, other, other_tenant, calls) == Outcome(skipped="nothing_to_diagnose")

    await prefs.set_enabled(db_session, user_id, prefs.DIAGNOSIS, False)
    await db_session.commit()
    assert await _run(app, user_id, tenant_id, calls) == Outcome(skipped="disabled")

    await prefs.set_enabled(db_session, user_id, prefs.DIAGNOSIS, True)
    await db_session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(background_daily_tokens=0)
    )
    await db_session.commit()
    assert await _run(app, user_id, tenant_id, calls) == Outcome(skipped="budget_exhausted")

    assert calls.calls == []
    assert await _diagnoses(db_session, user_id) == []
