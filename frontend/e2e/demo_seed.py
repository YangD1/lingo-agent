"""Seed the demo account (task 72.3) on the E2E backend's database, for the screenshots:
`make demo-seed`'s own entry point, with run_backend's DATABASE_URL.
Run from frontend/: `uv run --project ../backend python e2e/demo_seed.py <password> <zh|en>`.
"""

import asyncio
import os
import sys

if __name__ == "__main__":
    here = os.path.dirname(__file__)
    sys.path.insert(0, os.path.join(here, "..", "..", "backend"))
    sys.path.insert(0, here)
    import run_backend  # noqa: F401  (sets the E2E backend's environment)

    from app.demo.seed import _main

    password, lang = sys.argv[1], sys.argv[2]
    sys.exit(asyncio.run(_main(["--password", password, "--lang", lang])))
