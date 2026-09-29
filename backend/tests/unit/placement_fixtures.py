"""A made-up word pool over every band of the real rules, for placement tests."""

from app.adaptive.placement.words import WordPool, build_pool
from app.adaptive.rules import get_rules


def full_pool(per_band: int = 30) -> WordPool:
    vr = get_rules().placement.vocab
    rows = [
        (rank, "w" + "".join(chr(97 + int(d)) for d in str(rank)), rank, None)
        for rank in range(1, vr.max_rank + 1, vr.band_size // per_band)
    ]
    return build_pool(rows, vr)


POOL = full_pool()
