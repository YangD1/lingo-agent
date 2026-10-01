"""Picking Tatoeba sentences for words (ADR 0020): pure functions, no database."""

from app.services.vocab.import_tatoeba import Entry, Pair, Vocab, pair_up, pick

VOCAB = Vocab.of(
    [
        Entry(1, "go", "p:went/d:gone/i:going/3:goes", 30),
        Entry(2, "held", "0:hold/1:dp/p:held/d:held", 900),
        Entry(3, "hold", "p:held/d:held", 800),
        Entry(4, "look up", None, None),
        Entry(5, "china", None, 9000),
        Entry(6, "English", None, 600),
        Entry(7, "meticulous", None, 15000),
        Entry(8, "the", None, 1),
        Entry(9, "to", None, 2),
        Entry(10, "I", None, 5),
        Entry(11, "school", None, 400),
        Entry(12, "home", None, 300),
        Entry(13, "word", None, 700),
        Entry(14, "a", None, 3),
        Entry(15, "is", None, 4),
        Entry(16, "with", None, 6),
    ]
)


def ids(picked: dict[int, list[Pair]], word_id: int) -> list[int]:
    return [p.id for p in picked.get(word_id, [])]


def test_pair_up_prefers_a_simplified_translation_and_converts_otherwise() -> None:
    simplify = {"我們走吧。": "我们走吧。"}.get
    pairs = pair_up(
        [(11, 1), (12, 1), (13, 2)],
        {1: "Let's go home now.", 2: "I went to school.", 3: "Untranslated."},
        {11: "我們走吧。", 12: "咱们走吧。", 13: "我們走吧。"},
        lambda s: simplify(s) or s,
    )
    assert pairs == [
        Pair(1, "Let's go home now.", "咱们走吧。"),
        Pair(2, "I went to school.", "我们走吧。"),
    ]


def test_inflections_and_phrases_match_but_not_the_lemma_of_an_inflected_entry() -> None:
    picked = pick(
        [
            Pair(1, "I went to school.", ""),
            Pair(2, "I hold the word at school.", ""),
            Pair(3, "I held the word.", ""),
            Pair(4, "I look up the word.", ""),
        ],
        VOCAB,
    )
    assert ids(picked, 1) == [1]
    assert ids(picked, 2) == [3]  # "held" is not shown "hold"
    assert sorted(ids(picked, 3)) == [2, 3]  # "hold" is shown "held"
    assert ids(picked, 4) == [4]


def test_names_neither_match_nor_count_and_capitalised_words_match_exactly() -> None:
    picked = pick(
        [
            Pair(1, "I went to China with Tom.", ""),
            Pair(2, "I is a china word.", ""),
            Pair(3, "I go to English school.", ""),
            Pair(4, "English is the word.", ""),
            Pair(5, "I go to meticulous school.", ""),
        ],
        VOCAB,
    )
    assert ids(picked, 5) == [2]
    assert sorted(ids(picked, 6)) == [3, 4]
    # "China" and "Tom" are names, not uncommon words, so 1 ranks with 3 and above 5.
    assert ids(picked, 1) == [1, 3]


def test_ranks_by_uncommon_words_then_length_keeps_two_and_drops_repeats() -> None:
    picked = pick(
        [
            Pair(1, "I go.", ""),  # too short
            Pair(2, "I go to the meticulous school.", ""),  # one uncommon word
            Pair(3, "I go to the school.", ""),
            Pair(4, "I go home to the school to the home to the word.", ""),
            Pair(5, "i go to the school.", ""),  # same wording as 3
            Pair(7, "I go to a school.", ""),  # the same as 3 but for one word
            Pair(6, " ".join(["go"] * 21), ""),  # too long
        ],
        VOCAB,
    )
    # 3 and 4 have no uncommon word; 4 (12 words) is closer to 9 than 3 (5 words).
    assert ids(picked, 1) == [4, 3]
    # The word itself never counts as uncommon.
    assert ids(picked, 7) == [2]
