"""Run the evaluation sets: `python -m evals [name ...] [--live --email E [--record]]`.

Replay (the default) needs no database and no key. `--live` calls the real models of
the tenant the account `--email` belongs to in the database of `DATABASE_URL` (the dev
database), through the provider layer; `--record` then rewrites the cassettes of the
datasets it ran. Exit status: 0 every threshold met, 1 some not, 2 a stale recording.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.auth.service import normalize_email
from app.db.models import TenantMember, User
from app.db.session import create_engine, create_sessionmaker
from app.providers.config import TenantProviderContext
from app.providers.tenant import load_provider_context
from app.settings import get_settings
from evals.models import CASSETTES_DIR, Cassette, CassetteMiss, EvalModel, LiveModel, ReplayModel
from evals.registry import EVALUATORS
from evals.runner import evaluate


async def tenant_context(email: str) -> TenantProviderContext:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            tenant_id = await session.scalar(
                select(TenantMember.tenant_id)
                .join(User, User.id == TenantMember.user_id)
                .where(User.email == normalize_email(email))
                .order_by(TenantMember.created_at)
                .limit(1)
            )
            if tenant_id is None:
                raise SystemExit(f"no account {email!r} in {engine.url.database}")
            return await load_provider_context(session, tenant_id)
    finally:
        await engine.dispose()


async def run(names: Sequence[str], email: str | None, record: bool) -> int:
    ctx = await tenant_context(email) if email is not None else None
    status = 0
    for name in names:
        cassette: Cassette | None = None
        model: EvalModel
        if ctx is None:
            model = ReplayModel(Cassette.load(name))
        else:
            cassette = Cassette(CASSETTES_DIR / f"{name}.json") if record else None
            model = LiveModel(ctx, cassette)
        try:
            report = await evaluate(EVALUATORS[name], model)
        except CassetteMiss as e:
            print(f"== {name} ==\n{e}")
            status = 2
            continue
        print(report.render())
        if cassette is not None:
            if report.errors:
                print(f"  not recorded: {len(report.errors)} call(s) failed")
            else:
                cassette.save()
                print(f"  recorded {len(cassette.entries)} call(s) to {cassette.path}")
        if not report.met:
            status = max(status, 1)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("names", nargs="*", help=f"of {', '.join(EVALUATORS)}; default: all")
    parser.add_argument("--live", action="store_true", help="call the real models")
    parser.add_argument("--email", help="--live: the account whose tenant's models to use")
    parser.add_argument("--record", action="store_true", help="--live: rewrite the cassettes")
    args = parser.parse_args()
    if args.live != (args.email is not None) or (args.record and not args.live):
        parser.error("--live needs --email, and --email and --record need --live")
    if unknown := set(args.names) - set(EVALUATORS):
        parser.error(f"unknown evaluator(s): {', '.join(sorted(unknown))}")
    names = args.names or list(EVALUATORS)
    if not names:
        print("no evaluators registered")
        return
    sys.exit(asyncio.run(run(names, args.email, args.record)))


if __name__ == "__main__":
    main()
