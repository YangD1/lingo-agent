"""Run the `word_examples_prefetch` job (task 44) for one learner, against the E2E backend's
database. The E2E backend runs with the scheduler off, and a run for every tenant would
touch other tests' learners, so tests call this for their own account.
Run from frontend/: `uv run --project ../backend python e2e/prefetch_examples.py <email>`.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime


async def main(email: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.adaptive.rules import get_rules
    from app.db.models import TenantMember, User
    from app.services.vocab.prefetch import prefetch_tenant

    engine = create_async_engine(os.environ["DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        member = (
            await session.execute(
                select(TenantMember.tenant_id, TenantMember.user_id)
                .join(User, User.id == TenantMember.user_id)
                .where(User.email == email)
            )
        ).one()
    written = await prefetch_tenant(
        maker, member.tenant_id, [member.user_id], rules=get_rules(), now=datetime.now(UTC)
    )
    print(f"{written} words written")
    await engine.dispose()


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    sys.path.insert(0, os.path.join(here, "..", "..", "backend"))
    sys.path.insert(0, here)
    import run_backend  # noqa: F401  (sets the E2E backend's environment)

    asyncio.run(main(sys.argv[1]))
