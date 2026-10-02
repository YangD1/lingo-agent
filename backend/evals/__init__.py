"""Minimal evaluation sets for the model calls that guard what learners see (P2 Q13).

Each evaluator runs a dataset (`datasets/<name>.yaml`) through the same code path as
the app, against an `EvalModel`: by default one that replays outputs recorded from a
real model (`cassettes/<name>.json`), optionally the real model of a tenant from the
dev database. See `README.md`.
"""
