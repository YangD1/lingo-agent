import re
from pathlib import Path

import pytest

from app.adaptive.placement.pseudowords import (
    ECDICT_PATH,
    MAX_LEN,
    MIN_LEN,
    PSEUDOWORDS_PATH,
    build,
    get_pseudowords,
    pronounceable,
    read_ecdict,
    rejection,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ecdict_sample.csv"
TRAINING = (
    "house", "table", "garden", "window", "letter", "market", "planet", "winter", "summer",
    "number", "person", "family", "animal", "flower", "silver", "basket", "candle", "pocket",
    "rabbit", "ticket", "turtle", "butter", "castle", "circle", "forest", "island", "button",
)  # fmt: skip


@pytest.mark.parametrize(
    ("word", "reason"),
    [
        ("abc", "length"),
        ("abcdefghijk", "length"),
        ("Hause", "length"),
        ("strchkla", "unpronounceable"),
        ("fuckle", "offensive"),
        ("updation", "excluded on review"),
        ("house", "real word"),
        ("snowable", "real word + suffix"),
        ("hopeful", "real word + suffix"),
        ("mistable", "prefix + real word"),
        ("tablely", "real word + suffix"),
        ("gardenpa", "common word + ending"),
        ("hause", "one edit from a common word"),
        ("brinjohnny", "length"),
        ("zojohnnyk", "contains a name"),
        ("plimber", None),
    ],
)
def test_rejection(word: str, reason: str | None) -> None:
    lexicon = frozenset({"house", "snow", "hope", "table", "garden"})
    common = frozenset({"house", "garden"})
    assert rejection(word, lexicon, common, frozenset({"johnny"})) == reason


def test_pronounceable() -> None:
    assert pronounceable("blimber")
    assert not pronounceable("bcdf")  # no vowel
    assert not pronounceable("strchk")  # four consonants
    assert not pronounceable("beaiut")  # three vowels


def test_build_is_reproducible_and_filtered() -> None:
    lexicon = frozenset(TRAINING)
    first = build(TRAINING, lexicon, lexicon, frozenset(), count=3, seed=7)
    assert first == build(TRAINING, lexicon, lexicon, frozenset(), count=3, seed=7)
    assert len(set(first)) == 3
    assert all(rejection(w, lexicon, lexicon) is None for w in first)


def test_build_gives_up_when_nothing_qualifies() -> None:
    with pytest.raises(RuntimeError, match="pseudo-words found"):
        build(("abcd",), frozenset({"abcd"}), frozenset(), frozenset(), count=1)


def test_read_ecdict_collects_forms_and_names() -> None:
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        lexicon = read_ecdict(f)
    assert "abandon" in lexicon.all_forms
    assert "abandoned" in lexicon.all_forms  # from the exchange column
    assert "hood" not in lexicon.all_forms  # "'hood" is not a plain word
    assert all(len(w) >= MIN_LEN for w in lexicon.training)
    assert lexicon.common <= lexicon.all_forms


def test_shipped_list() -> None:
    words = get_pseudowords()
    assert len(words) >= 200
    assert len(set(words)) == len(words)
    assert all(re.fullmatch(rf"[a-z]{{{MIN_LEN},{MAX_LEN}}}", w) for w in words)
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        lexicon = read_ecdict(f)
    assert not set(words) & lexicon.all_forms


@pytest.mark.skipif(not ECDICT_PATH.exists(), reason="full ECDICT not downloaded")
def test_shipped_list_matches_generator() -> None:
    """Regenerating from the full ECDICT gives the checked-in list: nobody edited it."""
    header = PSEUDOWORDS_PATH.read_text(encoding="utf-8").splitlines()[1]
    count, seed = (int(n) for n in re.findall(r"--(?:count|seed) (\d+)", header))
    with ECDICT_PATH.open(encoding="utf-8", newline="") as f:
        lexicon = read_ecdict(f)
    words = build(lexicon.training, lexicon.all_forms, lexicon.common, lexicon.names, count, seed)
    assert sorted(words) == list(get_pseudowords())
