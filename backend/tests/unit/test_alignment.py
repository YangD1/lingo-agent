import pytest

from app.services.speech.alignment import AlignedWord, compare


def statuses(reference: str, transcript: str) -> list[tuple[str, str, str | None]]:
    return [(w.word, w.status, w.heard) for w in compare(reference, transcript).words]


def test_a_perfect_reading_matches_every_word() -> None:
    result = compare("Good morning, everyone!", "good morning everyone")
    assert [w.status for w in result.words] == ["none", "none", "none"]
    assert (result.matched, result.total) == (3, 3)
    assert result.recognized_text == "good morning everyone"


def test_omission_substitution_and_insertion() -> None:
    assert statuses("I would like a cup of tea.", "I like a cup of the tea please") == [
        ("I", "none", None),
        ("would", "omission", None),
        ("like", "none", None),
        ("a", "none", None),
        ("cup", "none", None),
        ("of", "none", None),
        ("the", "insertion", None),
        ("tea", "none", None),
        ("please", "insertion", None),
    ]
    assert statuses("She sells sea shells.", "She sell sea shells") == [
        ("She", "none", None),
        ("sells", "substitution", "sell"),
        ("sea", "none", None),
        ("shells", "none", None),
    ]


def test_words_heard_before_the_sentence_starts_come_first() -> None:
    assert statuses("Thank you.", "um thank you")[0] == ("um", "insertion", None)


@pytest.mark.parametrize(
    ("reference", "transcript"),
    [
        ("Don't worry.", "do not worry"),
        ("I do not know.", "I don't know"),
        ("We're late.", "we are late"),
        ("I won" + chr(0x2019) + "t go.", "I will not go"),  # curly apostrophe
        ("I have 5 cats.", "I have five cats"),
        ("It's fine.", "it's fine"),  # ambiguous contractions are compared as written
    ],
)
def test_normalized_forms_match(reference: str, transcript: str) -> None:
    result = compare(reference, transcript)
    assert all(w.status == "none" for w in result.words), result.words
    assert result.matched == result.total


def test_half_a_contraction_is_heard_as_another_word() -> None:
    assert statuses("I don't know.", "I do know")[1] == ("don't", "substitution", "do")


def test_nothing_heard() -> None:
    result = compare("Hello there.", "")
    assert result.words == (
        AlignedWord(word="Hello", status="omission"),
        AlignedWord(word="there", status="omission"),
    )
    assert (result.matched, result.total) == (0, 2)
