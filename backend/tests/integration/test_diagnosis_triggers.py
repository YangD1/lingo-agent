"""When a learner is diagnosed: weekly by the daily job, and after a practice set
(task 46.4, Q46b)."""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.diagnosis import service, triggers
from app.adaptive.diagnosis.triggers import DiagnosisWorker, diagnose_due, due
from app.adaptive.graph_sync import sync_kc_edges
from app.adaptive.rules import get_rules
from app.db.models import Diagnosis, KCEvidence, Tenant
from app.scheduler import jobs
from app.scheduler.jobs import JobContext
from tests.integration.test_diagnosis_context import CATALOG, NOW, _mistakes
from tests.integration.test_diagnosis_service import FakeCalls
from tests.integration.test_word_examples_prefetch import learner

RULES = get_rules()  # interval_days 7; after a set: 20 hours and 3 new mistakes


def _diagnosis(user_id: uuid.UUID, when: datetime, evidence_upto: int | None) -> Diagnosis:
    return Diagnosis(
        user_id=user_id,
        trigger="weekly",
        target_kc_ids=["g.one"],
        root_causes=[],
        language="zh",
        evidence_upto=evidence_upto,
        rules_version=RULES.version,
        created_at=when,
    )


async def _newest_evidence(session: AsyncSession) -> int:
    await session.flush()
    newest = await session.scalar(select(KCEvidence.id).order_by(KCEvidence.id.desc()).limit(1))
    assert newest is not None
    return newest


async def test_weekly_needs_a_week_and_new_mistakes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, _ = await learner(client, db_session, model=False)
    db_session.add_all(_mistakes(user_id, "g.one", 2))
    await db_session.flush()
    # Never diagnosed: a KC needs min_mistakes first.
    assert not await due(db_session, user_id, "weekly", rules=RULES, now=NOW)
    db_session.add_all(_mistakes(user_id, "g.one", 1, days_ago=0.5))
    assert await due(db_session, user_id, "weekly", rules=RULES, now=NOW)

    db_session.add(_diagnosis(user_id, NOW - timedelta(days=6), await _newest_evidence(db_session)))
    await db_session.flush()
    assert not await due(db_session, user_id, "weekly", rules=RULES, now=NOW)
    # A week on, but nothing new since.
    later = NOW + timedelta(days=1)
    assert not await due(db_session, user_id, "weekly", rules=RULES, now=later)
    # One new counted mistake is enough once diagnosed before.
    db_session.add_all(_mistakes(user_id, "g.two", 1, days_ago=-0.5))
    assert await due(db_session, user_id, "weekly", rules=RULES, now=later)


async def test_after_a_set_needs_a_day_and_enough_new_mistakes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, _ = await learner(client, db_session, model=False)
    db_session.add_all(_mistakes(user_id, "g.one", 3, days_ago=2))
    db_session.add(
        _diagnosis(user_id, NOW - timedelta(hours=19), await _newest_evidence(db_session))
    )
    db_session.add_all(_mistakes(user_id, "g.two", 3, days_ago=0.1))
    await db_session.flush()
    assert not await due(db_session, user_id, "after_set", rules=RULES, now=NOW)
    later = NOW + timedelta(hours=1)
    assert await due(db_session, user_id, "after_set", rules=RULES, now=later)

    # Two new mistakes are too few; the older three came before the diagnosis.
    other, _ = await learner(client, db_session, model=False)
    db_session.add_all(_mistakes(other, "g.one", 3, days_ago=2))
    db_session.add(_diagnosis(other, NOW - timedelta(days=1), await _newest_evidence(db_session)))
    db_session.add_all(_mistakes(other, "g.two", 2, days_ago=0.1))
    await db_session.flush()
    assert not await due(db_session, other, "after_set", rules=RULES, now=NOW)


async def test_the_daily_job_diagnoses_learners_who_are_due(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me, _ = await learner(client, db_session, model=False)
    quiet, _ = await learner(client, db_session, model=False)
    db_session.add_all([*_mistakes(me, "g.one", 3), *_mistakes(quiet, "g.one", 1)])
    await db_session.commit()
    calls = FakeCalls()
    monkeypatch.setattr(service, "structured_call", calls)
    monkeypatch.setattr(jobs, "get_grammar_catalog", lambda: CATALOG)

    ctx = JobContext(app.state.sessionmaker, NOW, uuid.uuid4(), None)
    assert await jobs.diagnosis(ctx) is None

    rows = list(await db_session.scalars(select(Diagnosis)))
    assert [(r.user_id, r.trigger) for r in rows] == [(me, "weekly")]
    # Not due again the next day.
    ctx = JobContext(app.state.sessionmaker, NOW + timedelta(days=1), uuid.uuid4(), None)
    assert await jobs.diagnosis(ctx) is None
    assert len(calls.calls) == 1


async def test_the_daily_job_stops_at_the_budget_and_without_a_model(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me, tenant_id = await learner(client, db_session, model=False)
    db_session.add_all(_mistakes(me, "g.one", 3))
    await db_session.commit()
    sessionmaker = app.state.sessionmaker

    # No connection: the real call finds no model; nothing is stored, nothing raised.
    assert await diagnose_due(sessionmaker, rules=RULES, catalog=CATALOG, now=NOW) is None

    await db_session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(background_daily_tokens=0)
    )
    await db_session.commit()
    calls = FakeCalls()
    found = await diagnose_due(sessionmaker, rules=RULES, catalog=CATALOG, now=NOW, calls=calls)
    assert found == "budget_exhausted"
    assert calls.calls == []
    assert list(await db_session.scalars(select(Diagnosis))) == []


async def test_the_worker_diagnoses_after_a_set_when_due(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me, tenant_id = await learner(client, db_session, model=False)
    db_session.add_all(_mistakes(me, "g.one", 3))
    await db_session.commit()
    monkeypatch.setattr(triggers, "get_grammar_catalog", lambda: CATALOG)
    calls = FakeCalls()
    worker = DiagnosisWorker(app.state.sessionmaker, calls=calls, clock=lambda: NOW)

    worker.after_set(me, tenant_id)
    worker.after_set(me, tenant_id)  # one at a time
    await worker.wait_idle()
    # Done for today: the next set does not ask again.
    worker.after_set(me, tenant_id)
    await worker.wait_idle()

    rows = list(await db_session.scalars(select(Diagnosis)))
    assert [(r.user_id, r.trigger) for r in rows] == [(me, "after_set")]
    assert len(calls.calls) == 1

    off = DiagnosisWorker(app.state.sessionmaker, enabled=False, calls=calls)
    off.after_set(me, tenant_id)
    await off.wait_idle()
    assert len(calls.calls) == 1
