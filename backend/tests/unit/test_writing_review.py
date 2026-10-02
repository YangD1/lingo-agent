"""Splitting writing and checking the review model's output (task 38.1)."""

from typing import Any

from app.adaptive.kc.catalog import get_grammar_catalog
from app.writing.review import TASK, Review, check, review_messages, system_prompt
from app.writing.text import Sentence, sentences, word_count

TEXT = (
    "Last summer I go to Qingdao with my family. We swimmed every day!\n"
    "It was “great.” I want go again.\n\n"
    "Next year, maybe Xiamen? My sister's friend lives there."
)


def test_word_count_takes_contractions_and_hyphens_as_one_word() -> None:
    assert word_count("I don't like well-known places, 3 times.") == 6
    assert word_count("我喜欢 English") == 1


def test_sentences_are_numbered_with_their_paragraph() -> None:
    parts = sentences(TEXT)
    assert [(s.index, s.paragraph, s.text) for s in parts] == [
        (0, 0, "Last summer I go to Qingdao with my family."),
        (1, 0, "We swimmed every day!"),
        (2, 0, "It was “great.”"),
        (3, 0, "I want go again."),
        (4, 1, "Next year, maybe Xiamen?"),
        (5, 1, "My sister's friend lives there."),
    ]


def test_a_text_without_end_punctuation_is_one_sentence() -> None:
    assert sentences("  i like cats and dogs  ") == [Sentence(0, 0, "i like cats and dogs")]


def mistake(kc_id: str, original: str, **extra: Any) -> dict[str, Any]:
    return {
        "kc_id": kc_id,
        "error_type": "wrong_form",
        "severity": "medium",
        "original": original,
        "correction": "fixed",
        "explanation": "why",
    } | extra


def review(sentences: list[dict[str, Any]], vocab: list[str] | None = None) -> Review:
    score = {"score": 3, "reason": "ok"}
    return Review.model_validate(
        {
            "sentences": sentences,
            "scores": dict.fromkeys(("task", "coherence", "vocabulary", "grammar"), score),
            "summary": " Good start. ",
            "vocab_candidates": vocab or [],
        }
    )


def test_check_keeps_only_what_code_can_verify() -> None:
    parts = sentences(TEXT)
    checked = check(
        review(
            [
                {
                    "index": 0,
                    "corrected": "Last summer I went to Qingdao with my family.",
                    "mistakes": [
                        mistake("g.past_simple_irregular", " go "),  # trimmed, kept
                        mistake("g.past_simple_irregular", "go"),  # same again: dropped
                        mistake("g.not_in_catalog", "summer"),  # unknown KC: dropped
                        mistake("g.articles_basic", "the family"),  # not in it: dropped
                    ],
                },
                {
                    "index": 1,
                    "corrected": "We swam every day!",
                    "mistakes": [mistake("g.past_simple_irregular", "swimmed")],
                },
                {"index": 1, "corrected": "ignored repeat", "mistakes": []},
                {"index": 3, "corrected": "I want go again.", "mistakes": []},  # unchanged
                {
                    "index": 9,
                    "corrected": "no such sentence",
                    "mistakes": [mistake("g.past_simple_irregular", "x")],
                },
            ],
            vocab=["swim", "two words", "Swim", "a", "b", "c", "d", "e"],
        ),
        parts,
        get_grammar_catalog(),
    )

    first, second, third, fourth = checked.corrections[:4]
    assert first["corrected"] == "Last summer I went to Qingdao with my family."
    assert [m["original"] for m in first["mistakes"]] == ["go"]  # type: ignore[index, union-attr]
    assert second["corrected"] == "We swam every day!"
    assert third == {
        "index": 2,
        "paragraph": 0,
        "original": "It was “great.”",
        "corrected": None,
        "mistakes": [],
    }
    assert fourth["corrected"] is None
    assert len(checked.corrections) == len(parts)
    assert checked.dropped == 4
    assert checked.summary == "Good start."
    assert set(checked.scores) == {"task", "coherence", "vocabulary", "grammar"}
    # One word each, once, at most five.
    assert checked.vocab == ["swim", "a", "b", "c", "d"]


def test_messages_number_the_sentences_and_carry_the_catalog() -> None:
    system, human = review_messages("Write about a trip.", sentences(TEXT), "A2", "zh")
    assert system.content == system_prompt()
    assert "g.past_simple_irregular" in str(system.content)
    body = str(human.content)
    assert "[1] We swimmed every day!" in body
    assert "Task: Write about a trip." in body and "Simplified Chinese" in body
    assert TASK == "writing_review"
    _, free = review_messages(" ", sentences(TEXT), "B1", "en")
    assert "none given" in str(free.content)
