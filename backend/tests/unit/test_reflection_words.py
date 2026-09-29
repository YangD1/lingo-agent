from app.memory.reflection import (
    MAX_WORDS_PER_PASS,
    Reflection,
    VocabCandidate,
    asked_words,
    system_prompt,
)

IDS = {"u1": "msg-a", "u2": "msg-b"}


def candidates(*pairs: tuple[str, str]) -> Reflection:
    return Reflection(vocab_candidates=[VocabCandidate(message=m, word=w) for m, w in pairs])


def test_single_words_from_known_messages_each_once() -> None:
    result = candidates(
        ("u1", " reluctant "),
        ("u2", "Reluctant"),  # the same word again
        ("u1", "look forward to"),  # a phrase
        ("u9", "hesitate"),  # no such message
        ("u2", "sister-in-law"),
        ("u2", "won't"),
        ("u2", "犹豫"),
    )
    assert asked_words(result, IDS) == [
        ("msg-a", "reluctant"),
        ("msg-b", "sister-in-law"),
        ("msg-b", "won't"),
    ]


def test_at_most_a_few_words_per_pass() -> None:
    result = candidates(*[("u1", f"word{chr(97 + i)}") for i in range(MAX_WORDS_PER_PASS + 3)])
    assert len(asked_words(result, IDS)) == MAX_WORDS_PER_PASS


def test_prompt_explains_which_words_to_collect() -> None:
    assert "## Words to learn (`vocab_candidates`)" in system_prompt()
