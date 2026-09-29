import random

import pytest

from app.adaptive.placement.vocab_size import bands
from app.adaptive.placement.words import build_pool, is_testable
from app.adaptive.rules import PlacementVocabRules


@pytest.fixture
def rules() -> PlacementVocabRules:
    return PlacementVocabRules(
        band_size=10,
        max_rank=30,
        questions=10,
        pseudo_share=0.25,
        steepness=3.0,
        prior_median=15,
        prior_log_sd=1.5,
        unreliable_false_alarm=0.4,
    )


@pytest.mark.parametrize(
    ("word", "exchange"),
    [
        ("go", "p:went/d:gone/i:going/3:goes/0:go"),
        # ECDICT lists these as forms of another word, but they have forms of their own.
        ("number", "s:numbers/d:numbered/p:numbered/i:numbering/0:numb/1:r/3:numbs"),
        ("better", "0:good/1:r/d:bettered/s:betters/i:bettering/p:bettered/3:betters"),
        ("cut", "d:cut/0:cut/1:dp/s:cuts/i:cutting/p:cut/3:cuts"),
        ("elk", None),
        ("sex", None),
    ],
)
def test_is_testable(word: str, exchange: str | None) -> None:
    assert is_testable(word, exchange)


@pytest.mark.parametrize(
    ("word", "exchange"),
    [
        ("went", "0:go/1:p"),
        ("terms", "0:term/1:s3"),
        # Its only form is itself.
        ("used", "0:use/1:dp/d:used/p:used"),
        ("Welsh", None),
        ("LSD", None),
        ("n't", None),
        ("o'clock", None),
        ("fuck", None),
    ],
)
def test_not_is_testable(word: str, exchange: str | None) -> None:
    assert not is_testable(word, exchange)


def test_pool_groups_by_band_and_drops_the_rest(rules: PlacementVocabRules) -> None:
    rows = [
        (1, "cat", 3, None),
        (2, "dog", 1, None),
        (3, "went", 5, "0:go/1:p"),
        (4, "Paris", 12, None),
        (5, "elk", 15, None),
        (6, "rare", 31, None),
    ]
    pool = build_pool(rows, rules)
    assert [[w.word for w in band] for band in pool.bands] == [["dog", "cat"], ["elk"], []]
    assert pool.band_words == [2, 1, 0]


def test_pick_skips_used_words_and_empty_bands(rules: PlacementVocabRules) -> None:
    pool = build_pool([(1, "cat", 3, None), (2, "dog", 1, None), (5, "elk", 15, None)], rules)
    b = bands(rules)
    rng = random.Random(0)
    assert pool.pick(b[0], used={1}, rng=rng).word == "dog"  # type: ignore[union-attr]
    assert pool.pick(b[0], used={1, 2}, rng=rng) is None
    assert pool.pick_nearest([b[2], b[0], b[1]], used={1, 2}, rng=rng).word == "elk"  # type: ignore[union-attr]
    assert pool.pick_nearest(b, used={1, 2, 5}, rng=rng) is None


def test_pick_is_reproducible(rules: PlacementVocabRules) -> None:
    rows = [(i, f"w{chr(97 + i)}", i, None) for i in range(1, 10)]
    pool = build_pool(rows, rules)
    band = bands(rules)[0]
    first = [pool.pick(band, (), random.Random(f"7:{n}")) for n in range(5)]
    again = [pool.pick(band, (), random.Random(f"7:{n}")) for n in range(5)]
    assert first == again
