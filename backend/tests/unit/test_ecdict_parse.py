"""Choosing and converting ECDICT rows (ADR 0011). The fixture holds real ECDICT rows
(MIT licence) plus a later duplicate of "go" and an entry without a gloss."""

from pathlib import Path

from app.services.vocab.import_ecdict import Stats, WordRow, read_subset

SAMPLE = Path(__file__).parents[1] / "fixtures" / "ecdict_sample.csv"


def rows() -> tuple[dict[str, WordRow], Stats]:
    stats = Stats()
    with SAMPLE.open(newline="", encoding="utf-8") as f:
        kept = {row.word: row for row in read_subset(f, stats)}
    return kept, stats


def test_keeps_exam_oxford_collins_and_frequent_words_only() -> None:
    kept, stats = rows()
    assert stats.read == 27 and stats.kept == len(kept) == 18
    assert set(kept) == {
        # exam lists, Oxford 3000, Collins stars
        "abandon", "colour", "go", "hello", "run", "the", "us", "in spite of",
        "perspicacious", "quixotic", "serendipity", "ubiquitous",
        "a.m.", "sister-in-law", "won't",
        # ranked in the top 30,000 only
        "held", "nanotube", "Worcestershire",
    }  # fmt: skip
    # Dropped: unranked phrases and rare words, rank beyond 30,000, no gloss.
    for word in ("take off", "zymurgy", "aardvark", "went", "'hood", "blankgloss"):
        assert word not in kept


def test_converts_fields() -> None:
    kept, _ = rows()
    abandon = kept["abandon"]
    assert abandon.tags == ["cet4", "cet6", "gk", "gre", "ky", "toefl"]
    assert abandon.oxford is True and abandon.collins == 3
    assert (abandon.bnc, abandon.frq) == (2057, 2182)
    # Escaped line breaks become real ones.
    assert abandon.translation.startswith("vt. 放弃, 抛弃")
    assert "\nn." in abandon.translation and "\\n" not in abandon.translation
    colour = kept["colour"]
    assert colour.frq is None and colour.bnc == 642
    held = kept["held"]
    assert held.tags == [] and held.collins == 0 and held.oxford is False


def test_the_first_of_duplicate_words_wins() -> None:
    kept, _ = rows()
    assert kept["go"].translation != "a later duplicate of go"
