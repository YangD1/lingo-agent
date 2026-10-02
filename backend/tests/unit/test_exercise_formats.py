from typing import Any

import pytest
from pydantic import ValidationError

from app.adaptive.exercise.formats import (
    FORMATS,
    SPECS,
    Choice4,
    ChoiceResponse,
    FindFix,
    FindFixResponse,
    TextResponse,
    normalize,
    parse_body,
    parse_response,
)
from app.adaptive.rules import get_rules

EXPLAIN = "Use the past simple with a finished time like 'yesterday'."

VALID: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "choice4": (
        {"stem": "I ___ him yesterday.", "options": ["saw", "see", "have seen", "seen"]},
        {"correct": "saw", "explanation": EXPLAIN},
    ),
    "cloze": (
        {"stem": "I ___ him yesterday.", "hint": "see"},
        {"accepted": ["saw"], "explanation": EXPLAIN},
    ),
    "find_fix": (
        {"segments": ["I ", "have seen ", "him ", "yesterday."]},
        {"wrong_segment": 1, "accepted": ["saw "], "explanation": EXPLAIN},
    ),
    "transform": (
        {"instruction": "Rewrite in the passive voice.", "source": "They built it in 1990."},
        {"accepted": ["It was built in 1990."], "explanation": EXPLAIN},
    ),
    "translate": (
        {"source": "我昨天见到了他。", "instruction": "Use the past simple."},
        {"accepted": ["I saw him yesterday."], "explanation": EXPLAIN},
    ),
    "rewrite_own": (
        {
            "instruction": "Correct your sentence.",
            "original": "I have seen him yesterday.",
            "evidence_id": 42,
        },
        {"accepted": ["I saw him yesterday."], "explanation": EXPLAIN},
    ),
}


def test_every_format_has_a_spec_and_a_valid_example() -> None:
    assert set(SPECS) == set(FORMATS) == set(VALID)
    for fmt, (content, answer) in VALID.items():
        body = parse_body(fmt, content, answer)
        assert body.format == fmt
        assert isinstance(body, SPECS[fmt].body)


def test_every_format_has_a_guess_rate() -> None:
    assert set(FORMATS) <= get_rules().elo.guess_by_format.keys()
    assert get_rules().mastery_gate.min_formats <= len(FORMATS)


def test_evidence_and_grading_by_format() -> None:
    assert SPECS["choice4"].evidence == ("recognition",)
    assert SPECS["find_fix"].evidence == ("recognition", "production")
    assert all(
        SPECS[f].evidence == ("production",) for f in ("transform", "translate", "rewrite_own")
    )
    assert {f for f in FORMATS if SPECS[f].grading == "model"} == {
        "transform",
        "translate",
        "rewrite_own",
    }


def bad(
    fmt: str, content: dict[str, Any] | None = None, answer: dict[str, Any] | None = None
) -> None:
    base_content, base_answer = VALID[fmt]
    with pytest.raises(ValidationError):
        parse_body(fmt, base_content | (content or {}), base_answer | (answer or {}))


@pytest.mark.parametrize(
    ("fmt", "content", "answer"),
    [
        ("choice4", {"stem": "I saw him yesterday."}, None),  # no blank
        ("choice4", {"stem": "I ___ him ___."}, None),  # two blanks
        ("choice4", {"options": ["saw", "Saw", "see", "seen"]}, None),  # duplicate option
        ("choice4", None, {"correct": "sees"}),  # answer not among options
        ("choice4", {"options": ["saw", "see", "seen"]}, None),  # three options
        ("cloze", None, {"accepted": []}),
        ("cloze", None, {"accepted": ["saw", "saw."]}),  # same after normalizing
        ("find_fix", {"segments": ["I ", "saw him."]}, None),  # too few pieces
        ("find_fix", None, {"wrong_segment": 4}),
        ("find_fix", None, {"accepted": ["Have seen"]}),  # "fix" equals the wrong piece
        ("transform", None, {"accepted": ["They built it in 1990"]}),  # unchanged
        ("rewrite_own", None, {"accepted": ["I have seen him yesterday"]}),
        ("rewrite_own", {"evidence_id": 0}, None),
        ("translate", None, {"explanation": ""}),
    ],
)
def test_rejects_malformed_items(
    fmt: str, content: dict[str, Any] | None, answer: dict[str, Any] | None
) -> None:
    bad(fmt, content, answer)


def test_rejects_unknown_format_and_extra_fields() -> None:
    content, answer = VALID["choice4"]
    with pytest.raises(ValidationError):
        parse_body("essay", content, answer)
    with pytest.raises(ValidationError):
        parse_body("choice4", content | {"image": "x.png"}, answer)


def test_find_fix_sentence_joins_segments() -> None:
    body = parse_body("find_fix", *VALID["find_fix"])
    assert isinstance(body, FindFix)
    assert body.content.sentence == "I have seen him yesterday."


def test_choice4_matches_the_placement_item_shape() -> None:
    # A placement item (stem, answer, three distractors) can serve as a fallback.
    body = Choice4.model_validate(
        {
            "content": {"stem": "They ___ happy.", "options": ["are", "is", "am", "be"]},
            "answer": {"correct": "are", "explanation": EXPLAIN},
        }
    )
    assert body.format == "choice4"


def test_responses_by_format() -> None:
    assert parse_response("choice4", {"choice": "saw"}) == ChoiceResponse(choice="saw")
    assert parse_response("find_fix", {"segment": 1, "fix": "saw "}) == FindFixResponse(
        segment=1, fix="saw "
    )
    assert parse_response("translate", {"text": "I saw him."}) == TextResponse(text="I saw him.")
    with pytest.raises(ValidationError):
        parse_response("choice4", {"text": "saw"})
    with pytest.raises(ValidationError):
        parse_response("cloze", {"text": ""})


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("I saw him.", "  i SAW   him "),
        ("don" + chr(0x2019) + "t", "don't"),
        ("Is it?", "is it"),
    ],
)
def test_normalize_ignores_case_spacing_quotes_and_final_stop(a: str, b: str) -> None:
    assert normalize(a) == normalize(b)


def test_normalize_keeps_real_differences() -> None:
    assert normalize("I saw him") != normalize("I seen him")
    assert normalize("an apple") != normalize("apple")
