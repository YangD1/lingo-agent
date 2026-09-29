"""Pseudo-words for the vocabulary-size test (ADR 0010 §4, P1 plan §6.1).

A learner who ticks "I know this" on a word that does not exist shows how much their
yes answers are inflated by guessing, and the estimate is corrected by that rate.
A useful pseudo-word looks like English, is not a word, and is not one letter away
from a common word (a learner would read "hause" as a typo of "house" and say yes
honestly).

Candidates come from a letter 4-gram model trained on common words, then are checked
against the whole of ECDICT (~770k entries plus inflected forms), not just the subset
in the database: a rare real word ticked as known would be counted as a false alarm.
Because the full ECDICT is only on the machine that runs the import, the list is built
offline and checked in: `python -m app.adaptive.placement.pseudowords`.
"""

import argparse
import csv
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.settings import REPO_ROOT

PSEUDOWORDS_PATH = Path(__file__).parent / "pseudowords.txt"
ECDICT_PATH = REPO_ROOT / "data" / "ecdict.csv"

START, END = "^", "$"
ORDER = 4  # letter 4-grams: the next letter depends on the three before it
MIN_LEN, MAX_LEN = 4, 9
TRAIN_RANK = 20_000  # train on words ranked this common or better
COMMON_RANK = 10_000  # candidates one edit away from these are rejected

_WORD = re.compile(r"^[a-z]+$")
_VOWELS = frozenset("aeiouy")
# Real word + one of these is left out: a learner can work out "snowable" from "snow"
# and honestly say they know it.
_SUFFIXES = (
    "s", "es", "ed", "d", "ing", "er", "ers", "est", "ly", "y", "ness", "ful", "less",
    "able", "ably", "al", "ance", "ation", "ence", "hood", "ic", "ish", "ism", "ist",
    "ity", "ive", "ize", "ise", "ment", "ous", "ship",
)  # fmt: skip
_PREFIXES = ("un", "re", "dis", "mis", "pre", "over", "out", "in", "im", "non")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
# A pseudo-word must not read as a slur or obscenity, even as part of a longer string.
_OFFENSIVE = (
    "bitch", "cock", "crap", "cunt", "dick", "fag", "fuck", "nazi", "nigg", "piss", "porn", "rape",
    "sex", "shit", "slut", "twat", "whore",
)  # fmt: skip

# Rejected by hand when reviewing the generated list: reads as a name or brand, is a
# word in another language learners may know, is regional English, or is a fragment.
_EXCLUDED = frozenset({
    "certo", "eque", "favorece", "filitz", "herwick", "homann", "johnnyson", "libere",
    "michlorem", "pepsident", "recognify", "republism", "samsonate", "soybe", "studible",
    "succeless", "theodola", "unre", "updation",
})  # fmt: skip

Model = dict[str, Counter[str]]


def train(words: Iterable[str]) -> Model:
    model: Model = defaultdict(Counter)
    for word in words:
        padded = START * (ORDER - 1) + word + END
        for i in range(len(padded) - ORDER + 1):
            model[padded[i : i + ORDER - 1]][padded[i + ORDER - 1]] += 1
    return dict(model)


def generate(model: Model, rng: random.Random) -> str | None:
    """One letter string from the model, or None if it ran past MAX_LEN."""
    context, letters = START * (ORDER - 1), list[str]()
    while len(letters) <= MAX_LEN:
        counts = model[context]
        letter = rng.choices(list(counts), weights=list(counts.values()))[0]
        if letter == END:
            return "".join(letters)
        letters.append(letter)
        context = context[1:] + letter
    return None


def pronounceable(word: str) -> bool:
    """Has a vowel, and no run of more than three consonants or two vowels."""
    run_c = run_v = 0
    for ch in word:
        if ch in _VOWELS:
            run_v, run_c = run_v + 1, 0
        else:
            run_c, run_v = run_c + 1, 0
        if run_c > 3 or run_v > 2:
            return False
    return any(ch in _VOWELS for ch in word)


def one_edit_away(word: str) -> set[str]:
    """Every string one deletion, substitution, insertion or swap away."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    return (
        {a + b[1:] for a, b in splits if b}
        | {a + c + b[1:] for a, b in splits if b for c in _ALPHABET}
        | {a + c + b for a, b in splits for c in _ALPHABET}
        | {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
    ) - {word}


def rejection(
    word: str,
    lexicon: AbstractSet[str],
    common: AbstractSet[str],
    names: AbstractSet[str] = frozenset(),
) -> str | None:
    """Why `word` is not a usable pseudo-word, or None if it is.

    `lexicon` is every known word and form, `common` the frequent words, `names` the
    lowercased proper nouns (a string containing one reads as a name or brand).
    """
    if not MIN_LEN <= len(word) <= MAX_LEN or not _WORD.match(word):
        return "length"
    if not pronounceable(word):
        return "unpronounceable"
    if any(bad in word for bad in _OFFENSIVE):
        return "offensive"
    if word in _EXCLUDED:
        return "excluded on review"
    if word in lexicon:
        return "real word"
    for suffix in _SUFFIXES:
        stem = word.removesuffix(suffix)
        if stem != word and len(stem) >= 3 and (stem in lexicon or stem + "e" in lexicon):
            return "real word + suffix"
    # "adjustle": a common word plus a letter or two reads as a misprint of it.
    if any(word[:n] in common for n in range(max(4, len(word) - 2), len(word))):
        return "common word + ending"
    for prefix in _PREFIXES:
        rest = word.removeprefix(prefix)
        if rest != word and len(rest) >= 3 and rest in lexicon:
            return "prefix + real word"
    if not common.isdisjoint(one_edit_away(word)):
        return "one edit from a common word"
    if any(word[i:j] in names for i in range(len(word)) for j in range(i + 5, len(word) + 1)):
        return "contains a name"
    return None


def build(
    training: Sequence[str],
    lexicon: AbstractSet[str],
    common: AbstractSet[str],
    names: AbstractSet[str],
    count: int,
    seed: int = 0,
) -> list[str]:
    """`count` distinct pseudo-words, the same list for the same inputs and seed."""
    model = train(training)
    rng = random.Random(seed)
    found: list[str] = []
    seen: set[str] = set()
    for _ in range(count * 1000):
        if len(found) == count:
            return found
        word = generate(model, rng)
        if word is None or word in seen:
            continue
        seen.add(word)
        if rejection(word, lexicon, common, names) is None:
            found.append(word)
    raise RuntimeError(f"only {len(found)} of {count} pseudo-words found")


@dataclass(frozen=True)
class Lexicon:
    all_forms: frozenset[str]
    training: tuple[str, ...]
    common: frozenset[str]
    names: frozenset[str]


def read_ecdict(lines: Iterable[str]) -> Lexicon:
    """Every single-word entry and inflected form, the frequency-ranked words and names."""
    forms: set[str] = set()
    names: set[str] = set()
    ranked: list[tuple[int, str]] = []
    for record in csv.DictReader(lines):
        word = record["word"].strip().lower()
        if _WORD.match(word):
            forms.add(word)
            if record["word"].strip()[0].isupper() and len(word) >= 5:
                names.add(word)
        for part in (record.get("exchange") or "").split("/"):
            _, _, form = part.partition(":")
            if _WORD.match(form := form.strip().lower()):
                forms.add(form)
        ranks = [int(v) for v in (record["frq"], record["bnc"]) if v.strip() and int(v) > 0]
        if ranks and _WORD.match(word) and record["word"].strip() == word:
            ranked.append((min(ranks), word))
    ranked.sort()
    training = tuple(
        dict.fromkeys(w for rank, w in ranked if rank <= TRAIN_RANK and MIN_LEN <= len(w))
    )
    common = frozenset(w for rank, w in ranked if rank <= COMMON_RANK)
    return Lexicon(frozenset(forms), training, common, frozenset(names))


@cache
def get_pseudowords() -> tuple[str, ...]:
    lines = PSEUDOWORDS_PATH.read_text(encoding="utf-8").splitlines()
    return tuple(line for line in lines if line and not line.startswith("#"))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=ECDICT_PATH, help="full ECDICT CSV")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if not args.csv.exists():
        sys.exit(f"{args.csv} not found; run `make vocab-import` once to download it")
    with args.csv.open(encoding="utf-8", newline="") as f:
        lexicon = read_ecdict(f)
    words = build(
        lexicon.training, lexicon.all_forms, lexicon.common, lexicon.names, args.count, args.seed
    )
    header = (
        "# Pseudo-words for the vocabulary-size test, generated by\n"
        f"# `python -m app.adaptive.placement.pseudowords --count {args.count} "
        f"--seed {args.seed}`\n"
        f"# against the full ECDICT ({len(lexicon.all_forms)} words and forms). Do not edit by "
        "hand;\n# to drop a word, add it to the generator's filters and regenerate.\n"
    )
    PSEUDOWORDS_PATH.write_text(header + "\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"wrote {len(words)} pseudo-words to {PSEUDOWORDS_PATH}")


if __name__ == "__main__":
    main()
