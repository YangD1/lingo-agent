"""Run the evaluation sets: `python -m evals [name ...] [--live --email E [--record]]`.

Replay (the default) needs no database and no key. `--live` calls the real models of
the tenant the account `--email` belongs to in the database of `DATABASE_URL` (the dev
database), through the provider layer; `--record` then rewrites the cassettes of the
datasets it ran and their score baselines (ADR 0033 §3). Replay must reproduce each
baseline exactly; `--update-baseline` accepts the replayed scores instead, after an
intended change to an evaluator. `--markdown` prints a table of scores for the CI job
summary. Exit status: 0 every threshold met and every replay at its baseline, 1 not,
2 a stale recording.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth.service import normalize_email
from app.db.models import TenantMember, User
from app.db.session import create_engine, create_sessionmaker
from app.providers.config import TenantProviderContext
from app.providers.tenant import load_provider_context
from app.settings import get_settings
from evals.baseline import Baseline, diff, load_baselines, markdown, save_baselines, scores
from evals.models import (
    CASSETTES_DIR,
    RERECORD_HINT,
    Cassette,
    CassetteMiss,
    EvalModel,
    LiveModel,
    ReplayModel,
)
from evals.registry import EVALUATORS
from evals.report import Report
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


async def run(
    names: Sequence[str], email: str | None, record: bool, update: bool, table: bool
) -> int:
    ctx = await tenant_context(email) if email is not None else None
    baselines = load_baselines()
    reports: dict[str, Report] = {}
    status = 0
    for name in names:
        cassette: Cassette | None = None
        model: EvalModel
        live: LiveModel | None = None
        if ctx is None:
            replayed = Cassette.load(name)
            if not replayed.path.exists():
                print(f"== {name} ==\nno recordings yet: record them with {RERECORD_HINT}")
                continue
            model = ReplayModel(replayed)
        else:
            cassette = Cassette(CASSETTES_DIR / f"{name}.json") if record else None
            model = live = LiveModel(ctx, cassette)
        try:
            report = await evaluate(EVALUATORS[name], model)
        except CassetteMiss as e:
            print(f"== {name} ==\n{e}")
            status = 2
            continue
        reports[name] = report
        if table:
            status = max(status, 0 if report.met else 1)
            continue
        print(report.render())
        changed = diff(report, baselines.get(name))
        if changed:
            print(f"  differs from the baseline in {name}:")
            print("\n".join(changed))
        if cassette is not None and live is not None:
            if report.errors:
                print(f"  not recorded: {len(report.errors)} call(s) failed")
            else:
                cassette.save()
                baselines[name] = Baseline(
                    metrics=scores(report),
                    models=tuple(sorted(live.models)),
                    recorded=datetime.now(UTC).date().isoformat(),
                    prompts=model.prompts,
                )
                save_baselines(baselines)
                print(f"  recorded {len(cassette.entries)} call(s) to {cassette.path}")
        elif ctx is None and changed:
            if update:
                old = baselines.get(name, Baseline(metrics={}))
                baselines[name] = replace(old, metrics=scores(report), prompts=model.prompts)
                save_baselines(baselines)
                print("  baseline updated")
            else:
                print("  replay must match the baseline: re-record, or --update-baseline")
                status = max(status, 1)
        if not report.met:
            status = max(status, 1)
    if table:
        print(markdown(reports, baselines))
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("names", nargs="*", help=f"of {', '.join(EVALUATORS)}; default: all")
    parser.add_argument("--live", action="store_true", help="call the real models")
    parser.add_argument("--email", help="--live: the account whose tenant's models to use")
    parser.add_argument("--record", action="store_true", help="--live: rewrite the cassettes")
    parser.add_argument(
        "--update-baseline", action="store_true", help="replay: accept the replayed scores"
    )
    parser.add_argument("--markdown", action="store_true", help="replay: print a score table")
    args = parser.parse_args()
    if args.live != (args.email is not None) or (args.record and not args.live):
        parser.error("--live needs --email, and --email and --record need --live")
    if args.live and (args.update_baseline or args.markdown):
        parser.error("--update-baseline and --markdown are for replay")
    if unknown := set(args.names) - set(EVALUATORS):
        parser.error(f"unknown evaluator(s): {', '.join(sorted(unknown))}")
    names = args.names or list(EVALUATORS)
    if not names:
        print("no evaluators registered")
        return
    sys.exit(asyncio.run(run(names, args.email, args.record, args.update_baseline, args.markdown)))


if __name__ == "__main__":
    main()
