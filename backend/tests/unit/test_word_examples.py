from app.db.models import Word
from app.services.vocab.examples import Example, keep_valid, uses_word, word_forms

GO = Word(word="go", translation="v. 去", exchange="i:going/p:went/d:gone/3:goes")


def test_forms_are_the_word_and_its_inflections() -> None:
    assert word_forms(GO) == {"go", "going", "went", "gone", "goes"}
    # "1:" lists the kinds of an inflected entry, not words.
    went = Word(word="went", translation="", exchange="0:go/1:p")
    assert word_forms(went) == {"went", "go"}
    assert word_forms(Word(word="Paris", translation="")) == {"paris"}


def test_a_sentence_uses_a_form_as_a_whole_word() -> None:
    forms = word_forms(GO)
    assert uses_word("She went home early.", forms)
    assert uses_word("Going out? GO!", forms)
    assert not uses_word("The gopher ate the goods.", forms)
    assert uses_word("Please look it up.", {"look up"}) is False
    assert uses_word("Please look up the word.", {"look up"})


def test_only_sentences_that_use_the_word_are_kept() -> None:
    kept = keep_valid(
        GO,
        [
            Example(en=" I go to school by bus. ", zh="我坐公交上学。"),
            Example(en="She likes tea.", zh="她喜欢茶。"),
        ],
    )
    assert kept == [{"en": "I go to school by bus.", "zh": "我坐公交上学。"}]
