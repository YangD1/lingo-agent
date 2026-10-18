"""Generator drafts → items, the critic's verdict, and the two calls' messages (ADR 0021 §3)."""

import json
import random
from typing import Any

import pytest
from langchain_core.messages import BaseMessage

from app.adaptive.exercise import drafts, messages
from app.adaptive.exercise.formats import FORMATS, Format
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs, OwnSentence
from app.adaptive.exercise.planner import PlannedItem
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.placement.items import Item, ItemBank
from app.adaptive.rules import get_rules

CATALOG, RULES = get_grammar_catalog(), get_rules()
KC_ID = "g.present_simple_third_person"
KC = CATALOG.get(KC_ID)
assert KC is not None
OWN = OwnSentence(evidence_id=42, original="She like tea.", correction="She likes tea.")
LEARNER = LearnerInputs(
    level="A2",
    ability=-1.5,
    states={},
    own_sentences={KC_ID: OWN},
    profile={"Occupation": "nurse"},
    facts=["Has a cat called Mochi."],
)
MIDDLE = {
    "vocabulary": "at_target",
    "syntax": "moderate",
    "cues": "partial",
    "distractors": "one_plausible",
}
HARD = {
    "vocabulary": "above_target",
    "syntax": "complex",
    "cues": "none",
    "distractors": "several_plausible",
}

DRAFTS: dict[Format, dict[str, Any]] = {
    "choice4": {
        "stem": "My brother ___ in a hospital.",
        "options": ["works", "work", "working", "is work"],
        "correct": "works",
    },
    "cloze": {"stem": "She ___ coffee every morning.", "hint": "drink", "accepted": ["drinks"]},
    "find_fix": {
        "segments": ["He ", "go ", "to work ", "by bus."],
        "wrong_segment": 1,
        "accepted": ["goes "],
    },
    "transform": {
        "instruction": "Rewrite with 'my sister' as the subject.",
        "source": "I play tennis on Sundays.",
        "accepted": ["My sister plays tennis on Sundays."],
    },
    "translate": {"source": "她每天走路上班。", "accepted": ["She walks to work every day."]},
    "rewrite_own": {
        "instruction": "Correct your sentence.",
        "accepted": ["She likes tea."],
    },
    "concept_choice": {
        "question": "为什么是 'works' 而不是 'work'",
        "options": ["主语是第三人称单数", "因为是过去时", "因为句子是疑问句", "两个都对"],
        "correct": "主语是第三人称单数",
    },
    "explain": {
        "question": "用你自己的话说说, 什么时候动词要加 -s",
        "key_points": ["主语是 he / she / it 或单数名词", "一般现在时"],
    },
}


def ratings(levels: dict[str, str] = MIDDLE) -> dict[str, dict[str, str]]:
    return {name: {"level": level, "reason": "because"} for name, level in levels.items()}


def brief(fmt: Format, position: int = 0, target: float = -2.5) -> ItemBrief:
    return ItemBrief(
        position,
        PlannedItem(KC_ID, fmt, target, "weak"),
        KC,
        OWN if fmt == "rewrite_own" else None,
    )


def draft(fmt: Format, position: int = 0, **changes: Any) -> drafts.Draft:
    data = {
        "position": position,
        "format": fmt,
        "explanation": "Third person singular takes -s.",
        "ratings": ratings(),
        **DRAFTS[fmt],
        **changes,
    }
    return drafts.draft_model(RULES).model_validate(data)  # type: ignore[return-value]


def review(position: int = 0, **changes: Any) -> drafts.Review:
    data = {
        "position": position,
        "own_answer": "works",
        "answer_ok": True,
        "tests_kc": True,
        "content_ok": True,
        "ratings": ratings(),
        **changes,
    }
    return drafts.review_model(RULES).model_validate(data)  # type: ignore[return-value]


def text(message: BaseMessage) -> str:
    assert isinstance(message.content, str)
    return message.content


# --- schemas ---


def test_schemas_use_no_tagged_unions() -> None:
    """Flat optional fields work with every provider's structured output; oneOf does not."""
    generated = drafts.generated_set_model(RULES, [brief(f, i) for i, f in enumerate(DRAFTS)])
    for model in (generated, drafts.critic_report_model(RULES)):
        schema = json.dumps(model.model_json_schema())
        assert "oneOf" not in schema and "discriminator" not in schema


def test_ratings_follow_the_rubric() -> None:
    model = drafts.ratings_model(RULES)
    assert set(model.model_fields) == set(RULES.difficulty.dimensions)
    with pytest.raises(ValueError):
        model.model_validate(ratings({**MIDDLE, "cues": "obvious"}))
    value, levels = drafts.difficulty(KC, model.model_validate(ratings(HARD)), RULES)
    assert levels == HARD
    assert value == pytest.approx(RULES.difficulty.cefr_anchor["A1"] + 0.4 + 0.4 + 0.3 + 0.4)


def test_each_position_shows_its_format_fields_as_required() -> None:
    """With one flat schema for every format, a weak model left a concept_choice's
    options out in every round (task 86.9)."""
    model = drafts.generated_set_model(RULES, [brief("concept_choice", 0), brief("cloze", 3)])
    schema = model.model_json_schema()
    assert schema["required"] == ["item_0", "item_3"]
    defs = schema["$defs"]
    concept = defs["Draft_concept_choice"]
    assert set(concept["properties"]) == {
        "question",
        "options",
        "correct",
        "explanation",
        "ratings",
    }
    assert concept["required"][:3] == ["question", "options", "correct"]
    assert concept["properties"]["options"]["type"] == "array"
    cloze = defs["Draft_cloze"]
    assert "hint" in cloze["properties"] and "hint" not in cloze["required"]


def test_a_left_out_field_or_item_is_parsed_and_sent_back() -> None:
    """The schema asks for every field, but a draft without one is still read, so that
    one item is rewritten instead of the whole call failing."""
    briefs = [brief("concept_choice", 0), brief("explain", 1)]
    output = drafts.generated_set_model(RULES, briefs).model_validate(
        {"item_0": {"question": "Why 'works'?", "explanation": "-s.", "ratings": ratings()}}
    )
    (found,) = drafts.drafts_in(output, briefs)
    assert (found.position, found.format, found.options) == (0, "concept_choice", None)
    with pytest.raises(drafts.DraftError, match="`options` is missing"):
        drafts.to_body(found, briefs[0], random.Random(0))


# --- drafts to items ---


@pytest.mark.parametrize("fmt", list(DRAFTS))
def test_each_format_assembles(fmt: Format) -> None:
    body = drafts.to_body(draft(fmt), brief(fmt), random.Random(0))
    assert body.format == fmt
    assert body.answer.explanation


def test_choice4_options_are_shuffled_and_keep_the_key() -> None:
    orders = {
        drafts.to_body(draft("choice4"), brief("choice4"), random.Random(seed)).content.options  # type: ignore[union-attr]
        for seed in range(20)
    }
    assert len(orders) > 1
    assert all(set(o) == set(DRAFTS["choice4"]["options"]) for o in orders)


def test_rewrite_own_takes_the_learner_sentence_from_code() -> None:
    body = drafts.to_body(
        draft("rewrite_own", source="Something the model made up."),
        brief("rewrite_own"),
        random.Random(0),
    )
    assert body.content.original == OWN.original  # type: ignore[union-attr]
    assert body.content.evidence_id == OWN.evidence_id  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("fmt", "changes", "problem"),
    [
        ("cloze", {"format": "choice4"}, "planned cloze"),
        ("choice4", {"stem": "My brother works in a hospital."}, "exactly one ___"),
        ("choice4", {"correct": "worked"}, "one of the options"),
        ("cloze", {"accepted": None}, "accepted"),
        ("find_fix", {"wrong_segment": 9}, "out of range"),
        ("transform", {"accepted": ["I play tennis on Sundays."]}, "differ from the source"),
        ("rewrite_own", {"accepted": ["She like tea"]}, "differ from the original"),
    ],
)
def test_invalid_drafts_say_why(fmt: Format, changes: dict[str, Any], problem: str) -> None:
    with pytest.raises(drafts.DraftError, match=problem):
        drafts.to_body(draft(fmt, **changes), brief(fmt), random.Random(0))


@pytest.mark.parametrize("fmt", list(DRAFTS))
def test_required_fields_are_enough_and_each_needed(fmt: Format) -> None:
    """The fields the generator is told to fill (task 86.9) are what assembling uses."""
    only = {f: DRAFTS[fmt][f] for f in drafts.REQUIRED[fmt]}
    nulls = {f: None for f in DRAFTS[fmt] if f not in only}
    drafts.to_body(draft(fmt, **nulls), brief(fmt), random.Random(0))
    for field in drafts.REQUIRED[fmt]:
        with pytest.raises(drafts.DraftError, match=f"`{field}` is missing"):
            drafts.to_body(draft(fmt, **{field: None}), brief(fmt), random.Random(0))


def test_a_missing_field_says_what_to_write() -> None:
    """A weak model left concept_choice options null three rounds running when told
    `concept_choice.content.options.0: Field required`."""
    with pytest.raises(drafts.DraftError) as caught:
        drafts.to_body(
            draft("concept_choice", options=None, correct=None),
            brief("concept_choice"),
            random.Random(0),
        )
    assert str(caught.value) == (
        "`options` is missing: concept_choice needs the four options, the correct one "
        "included; `correct` is missing: concept_choice needs the correct option, as written"
    )


def test_validation_errors_name_the_draft_field() -> None:
    with pytest.raises(drafts.DraftError) as caught:
        drafts.to_body(
            draft("choice4", options=["works", "work", "working"]),
            brief("choice4"),
            random.Random(0),
        )
    assert str(caught.value).startswith("`options`: ")
    assert "content" not in str(caught.value)


# --- the critic's verdict ---


def judge(fmt: Format, **changes: Any) -> drafts.Verdict:
    body = drafts.to_body(draft(fmt), brief(fmt), random.Random(0))
    generator, _ = drafts.difficulty(
        KC, drafts.ratings_model(RULES).model_validate(ratings()), RULES
    )
    return drafts.judge(body, KC, generator, review(**changes), RULES)


def test_an_item_the_critic_solves_and_likes_passes() -> None:
    verdict = judge("choice4", own_answer="Works.")
    assert verdict.ok and verdict.reasons == ()
    assert verdict.ratings == MIDDLE


def test_failed_checks_carry_the_critic_problems() -> None:
    verdict = judge("choice4", answer_ok=False, problems=["'is work' also fits?", " "])
    assert not verdict.ok
    assert verdict.reasons == ("answer is not right or not the only one", "'is work' also fits?")


def test_problems_alone_do_not_fail_an_item() -> None:
    assert judge("choice4", problems=["Could be shorter."]).ok


@pytest.mark.parametrize(
    ("fmt", "changes"),
    [
        ("choice4", {"own_answer": "work"}),
        ("cloze", {"own_answer": "drink"}),
        ("find_fix", {"own_answer": "goes ", "own_segment": 2}),
    ],
)
def test_closed_items_fail_when_the_critic_solves_them_differently(
    fmt: Format, changes: dict[str, Any]
) -> None:
    verdict = judge(fmt, **changes)
    assert not verdict.ok and "critic" in verdict.reasons[0]


def test_open_items_are_not_compared_with_the_critic_answer() -> None:
    assert judge("translate", own_answer="Every day she goes to work on foot.").ok


def test_critic_answers_matching_the_key_pass() -> None:
    assert judge("cloze", own_answer="Drinks").ok
    assert judge("find_fix", own_answer="goes", own_segment=1).ok


def test_difficulty_ratings_far_apart_fail_and_the_critic_rating_is_kept() -> None:
    verdict = judge("translate", own_answer="x", ratings=ratings(HARD))
    assert not verdict.ok
    assert "difficulty ratings disagree" in verdict.reasons[0]
    assert verdict.ratings == HARD


def test_by_position_keeps_the_first_of_the_wanted() -> None:
    first, again, other = review(0), review(0, own_answer="work"), review(5)
    assert drafts.by_position([first, again, other], [0, 1]) == {0: first}


# --- messages ---


def test_generate_messages_carry_the_brief_and_personal_context() -> None:
    _, human = messages.generate_messages([brief("rewrite_own", position=3)], LEARNER, RULES)
    body = text(human)
    assert "Learner's level (CEFR): A2" in body
    assert "Simplified Chinese" in body
    assert "Occupation: nurse" in body and "Mochi" in body
    assert '"position": 3' in body and KC_ID in body
    assert '"original": "She like tea."' in body and "She likes tea." in body
    assert "rejected" not in body


def test_each_brief_lists_the_fields_to_fill() -> None:
    _, human = messages.generate_messages([brief("concept_choice")], LEARNER, RULES)
    sent = json.loads(text(human).split("Items to write:\n")[1].split("\n\n")[0])
    assert sent[0]["fields"] == ["question", "options", "correct", "explanation"]


def test_generate_messages_send_rejected_drafts_back_with_reasons() -> None:
    rejected = {1: messages.Rejected({"stem": "old"}, ["two options fit"])}
    _, human = messages.generate_messages([brief("choice4", 1)], LEARNER, RULES, rejected)
    assert "two options fit" in text(human) and '"stem": "old"' in text(human)


def test_target_offset_is_what_the_rubric_can_reach() -> None:
    anchor = RULES.difficulty.cefr_anchor["A1"]
    assert messages.target_offset(brief("cloze", target=anchor + 0.3), RULES) == 0.3
    assert messages.target_offset(brief("cloze", target=anchor + 9), RULES) == pytest.approx(1.5)
    assert messages.target_offset(brief("cloze", target=anchor - 9), RULES) == pytest.approx(-1.3)


def test_critic_sees_no_closed_key_but_open_references() -> None:
    items = [
        (brief(fmt, i), drafts.to_body(draft(fmt, i), brief(fmt, i), random.Random(0)))
        for i, fmt in enumerate(["choice4", "cloze", "find_fix", "rewrite_own"])
    ]
    _, human = messages.critic_messages(items, LEARNER, RULES)
    body = text(human)
    assert "drinks" not in body  # the cloze key
    assert "wrong_segment" not in body and "goes " not in body  # the find_fix key
    assert "explanation" not in body and "correct" not in body
    assert "She likes tea." in body  # rewrite_own's reference answer
    assert "evidence_id" not in body and "42" not in body
    assert "Mochi" not in body and "nurse" not in body  # the critic gets no personal context


# --- understanding checks (ADR 0044 §3) ---


def test_check_drafts_make_items() -> None:
    choice = drafts.to_body(draft("concept_choice"), brief("concept_choice"), random.Random(0))
    assert choice.format == "concept_choice"
    assert sorted(choice.content.options) == sorted(DRAFTS["concept_choice"]["options"])
    explain = drafts.to_body(draft("explain"), brief("explain"), random.Random(0))
    assert explain.format == "explain"
    assert explain.answer.key_points == tuple(DRAFTS["explain"]["key_points"])  # type: ignore[union-attr]
    with pytest.raises(drafts.DraftError):
        drafts.to_body(draft("explain", key_points=[]), brief("explain"), random.Random(0))


def test_the_critic_solves_a_concept_question_without_its_key() -> None:
    body = drafts.to_body(draft("concept_choice"), brief("concept_choice"), random.Random(0))
    agreed = drafts.judge(body, KC, -2.5, review(own_answer="主语是第三人称单数"), RULES)
    assert agreed.ok
    other = drafts.judge(body, KC, -2.5, review(own_answer="因为是过去时"), RULES)
    assert not other.ok


def test_check_instructions_only_reach_sets_that_have_checks() -> None:
    plain, _ = messages.generate_messages([brief("choice4")], LEARNER, RULES)
    assert "Understanding checks" not in text(plain)
    checked, _ = messages.generate_messages(
        [brief("concept_choice", 0), brief("explain", 1)], LEARNER, RULES
    )
    assert "Understanding checks" in text(checked)
    items = [
        (brief(fmt, i), drafts.to_body(draft(fmt, i), brief(fmt, i), random.Random(0)))
        for i, fmt in enumerate(["concept_choice", "explain"])
    ]
    system, human = messages.critic_messages(items, LEARNER, RULES)
    assert "Understanding checks" in text(system)
    body = text(human)
    assert "主语是 he / she / it" in body  # explain's key points: the critic checks them
    assert "correct" not in body  # the concept question's key stays hidden


# --- the exercise-writing skill (ADR 0055 §2) ---


def test_only_the_guides_of_the_set_formats_are_spliced_in() -> None:
    system, _ = messages.generate_messages(
        [brief("cloze", 0), brief("transform", 1), brief("cloze", 2)], LEARNER, RULES
    )
    body = text(system)
    assert "Never give the tested form away" in body  # the skill's general rules
    assert body.index("# cloze:") < body.index("# transform:")  # catalog order, once each
    assert body.count("# cloze:") == 1
    for other in ("# choice4:", "# find_fix:", "# translate:", "# rewrite_own:"):
        assert other not in body
    assert "Understanding checks" not in body


def test_check_formats_get_the_understanding_checks_part_first() -> None:
    system, _ = messages.generate_messages(
        [brief("explain", 0), brief("choice4", 1)], LEARNER, RULES
    )
    body = text(system)
    assert (
        body.index("# Understanding checks") < body.index("# choice4:") < body.index("# explain:")
    )


def test_every_format_has_a_guide() -> None:
    for fmt in FORMATS:
        assert messages.writing_guide([fmt]).count(f"# {fmt}:") == 1, fmt


def bank_item(item_id: str, kc: str, difficulty: float) -> Item:
    return Item(
        id=item_id,
        kc=kc,
        cefr="A1",
        stem=f"Stem of {item_id} ___.",
        answer="works",
        distractors=("work", "working", "worked"),
        ratings={},
        difficulty=difficulty,
    )


def test_bank_items_on_the_set_grammar_points_are_examples_closest_first() -> None:
    bank = ItemBank(
        format="choice4",
        items=(
            bank_item("p.far", KC_ID, 1.0),
            bank_item("p.near", KC_ID, -2.4),
            bank_item("p.mid", KC_ID, -1.5),
            bank_item("p.other", "g.be_present", -2.5),
        ),
    )
    _, human = messages.generate_messages([brief("cloze", target=-2.5)], LEARNER, RULES, bank=bank)
    body = text(human)
    assert "Example items from the reviewed bank" in body
    assert body.index("Stem of p.near") < body.index("Stem of p.mid")
    assert "-> works (wrong: work, working, worked)" in body
    assert "p.far" not in body and "p.other" not in body


def test_no_examples_without_bank_items_on_the_grammar_point() -> None:
    other = ItemBank(format="choice4", items=(bank_item("p.other", "g.be_present", -2.5),))
    for bank in (None, other):
        _, human = messages.generate_messages([brief("cloze")], LEARNER, RULES, bank=bank)
        assert "Example items" not in text(human)
