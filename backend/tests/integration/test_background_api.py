"""Background work settings: learner switches, tenant budget, job status (ADR 0025 §5-6)."""

import uuid
from datetime import UTC, datetime, timedelta

from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, SchedulerRun, TenantMember
from app.scheduler import prefs
from app.scheduler.jobs import Job, JobContext
from app.scheduler.service import Scheduler


async def login(client: AsyncClient) -> uuid.UUID:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def tenant_of(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    return tenant_id


async def test_endpoints_require_login(client: AsyncClient) -> None:
    for path in ("/me/background", "/tenant/background"):
        assert (await client.get(path)).status_code == 401


async def test_learner_switches_default_and_persist(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await login(client)
    body = (await client.get("/me/background")).json()
    assert body == {
        "features": [
            {
                "key": "practice_prefetch",
                "enabled": True,
                "default": True,
                "usage_feature": "practice_set",
            },
            {
                "key": "article_prerewrite",
                "enabled": True,
                "default": True,
                "usage_feature": "reading_prerewrite",
            },
            {
                "key": "word_examples_prefetch",
                "enabled": True,
                "default": True,
                "usage_feature": "word_examples_prefetch",
            },
        ],
        "budget": "ok",
    }

    response = await client.put("/me/background/practice_prefetch", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["features"][0]["enabled"] is False
    assert not await prefs.is_enabled(db_session, user_id, prefs.PRACTICE_PREFETCH)
    # Switching again updates the same row.
    await client.put("/me/background/practice_prefetch", json={"enabled": True})
    assert (await client.get("/me/background")).json()["features"][0]["enabled"] is True

    response = await client.put("/me/background/nope", json={"enabled": False})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "feature_not_found"


async def test_switches_are_per_learner(client: AsyncClient, db_session: AsyncSession) -> None:
    first = await login(client)
    await client.put("/me/background/practice_prefetch", json={"enabled": False})
    second = await login(client)  # the client now acts as the second learner
    assert (await client.get("/me/background")).json()["features"][0]["enabled"] is True
    assert not await prefs.is_enabled(db_session, first, prefs.PRACTICE_PREFETCH)
    assert await prefs.is_enabled(db_session, second, prefs.PRACTICE_PREFETCH)


async def test_tenant_budget_and_todays_use(client: AsyncClient, db_session: AsyncSession) -> None:
    user_id = await login(client)
    tenant_id = await tenant_of(db_session, user_id)
    db_session.add(
        LLMUsage(
            tenant_id=tenant_id,
            task="exercise_generate",
            connection_name="c",
            model="m",
            input_tokens=700,
            output_tokens=300,
            latency_ms=1,
            status="ok",
            background=True,
        )
    )
    await db_session.commit()

    body = (await client.get("/tenant/background")).json()
    assert (body["daily_tokens"], body["used_today"], body["budget"]) == (100_000, 1000, "ok")
    assert body["scheduler_running"] is False

    body = (await client.put("/tenant/background", json={"daily_tokens": 1000})).json()
    assert (body["daily_tokens"], body["budget"]) == (1000, "exhausted")
    # The learner side only learns that it is used up, not the numbers.
    assert (await client.get("/me/background")).json()["budget"] == "exhausted"

    await client.put("/tenant/background", json={"daily_tokens": 0})
    assert (await client.get("/me/background")).json()["budget"] == "off"

    for bad in (-1, 100_000_001):
        response = await client.put("/tenant/background", json={"daily_tokens": bad})
        assert response.status_code == 422


async def noop(ctx: JobContext) -> str | None:
    return None


async def test_job_status_lists_jobs_defined_in_code(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    hourly = IntervalTrigger(hours=1, timezone=UTC)
    app.state.scheduler = Scheduler(
        app.state.sessionmaker, [Job("fetch_feeds", hourly, noop), Job("diagnose", hourly, noop)]
    )
    finished = datetime.now(UTC) - timedelta(minutes=5)
    db_session.add_all(
        [
            SchedulerRun(
                job="fetch_feeds",
                last_started_at=finished,
                last_finished_at=finished,
                last_status="skipped",
                last_skip_reason="budget_exhausted",
            ),
            # A job no longer in code is not shown.
            SchedulerRun(job="retired", last_started_at=finished, last_status="ok"),
        ]
    )
    await db_session.commit()

    jobs = (await client.get("/tenant/background")).json()["jobs"]
    assert [j["job"] for j in jobs] == ["fetch_feeds", "diagnose"]
    assert (jobs[0]["last_status"], jobs[0]["last_skip_reason"]) == ("skipped", "budget_exhausted")
    assert jobs[1]["last_status"] is None
    assert jobs[0]["next_run_at"] is None  # the scheduler is not started in tests
