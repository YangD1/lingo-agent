from app.services.reading.glossary import Entry, pick, tokens

ENTRIES = {
    "the": Entry(1, "the", 1),
    "scientists": Entry(2, "scientist", 4000),
    "scientist": Entry(2, "scientist", 4000),
    "found": Entry(3, "find", 200),
    "a": Entry(4, "a", 3),
    "comet": Entry(5, "comet", 12000),
    "orbit": Entry(6, "orbit", 7000),
    "orbiting": Entry(6, "orbit", 7000),
    "near": Entry(7, "near", 500),
    "mars": Entry(8, "mars", None),
    "obscure": Entry(9, "obscure", None),
}


def test_tokens_mark_sentence_starts_as_common() -> None:
    assert tokens(["The comet. Mars is near, said NASA."]) == [
        ("the", True),
        ("comet", True),
        ("mars", True),
        ("is", True),
        ("near", True),
        ("said", True),
        ("nasa", False),
    ]


def test_pick_lists_words_past_the_cut_in_order_of_first_use() -> None:
    text = [
        "Scientists found a comet orbiting the sun.",
        "The comet is near an orbit of an obscure moon. Another scientist agreed.",
    ]
    glossary = pick(text, ENTRIES, cut=3500, limit=10)
    assert glossary.words == [
        {"word": "scientist", "word_id": 2, "form": "scientists"},
        {"word": "comet", "word_id": 5, "form": "comet"},
        {"word": "orbit", "word_id": 6, "form": "orbiting"},
        {"word": "obscure", "word_id": 9, "form": "obscure"},
    ]
    # Lexicon words used: Scientists found a comet orbiting the | The comet near
    # orbit obscure scientist = 12; past the cut: scientists comet orbiting comet orbit
    # obscure scientist = 7.
    assert glossary.above_level_share == 7 / 12


def test_pick_skips_names_and_stops_at_the_limit() -> None:
    # "Mars" is capitalized mid-sentence every time: a name, though the lexicon has it.
    text = ["We saw Mars and a comet near Mars, then an orbit."]
    glossary = pick(text, ENTRIES, cut=3500, limit=1)
    assert [w["word"] for w in glossary.words] == ["comet"]
    assert glossary.above_level_share == 2 / 4


def test_pick_with_no_lexicon_words() -> None:
    glossary = pick(["Zzz qqq."], ENTRIES, cut=1000, limit=5)
    assert glossary.words == []
    assert glossary.above_level_share is None
