"""Places a skill on one continuous CEFR scale, so skills measured in different units
(grammar ability, known words) can be drawn side by side (P1 plan §7.5.1, Q17d).

Position 0 to 6: level i (A1 = 0 … C2 = 5) covers [i, i + 1), and a value's place between
its level's lower cut and the next one gives the fraction. A1 and C2 have one cut only,
so they borrow the width of their neighbouring level; the ends are clamped.
"""

from collections.abc import Mapping

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel

TOP = float(len(CEFR_LEVELS))


def position(value: float, cuts: Mapping[CefrLevel, float]) -> float:
    """`cuts`: the lower bound of each level from A2 to C2, rising."""
    bounds = [cuts[level] for level in CEFR_LEVELS[1:]]
    if value < bounds[0]:
        width = bounds[1] - bounds[0] or 1.0
        return max(0.0, 1.0 - (bounds[0] - value) / width)
    for i in range(len(bounds) - 1):
        if value < bounds[i + 1]:
            return i + 1 + (value - bounds[i]) / (bounds[i + 1] - bounds[i])
    width = bounds[-1] - bounds[-2] or 1.0
    return min(TOP, len(bounds) + (value - bounds[-1]) / width)
