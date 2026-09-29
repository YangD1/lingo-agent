from langchain_core.messages import AIMessage, HumanMessage

from app.adaptive.kc.catalog import get_grammar_catalog
from app.memory.reflection import (
    MAX_CORRECT_PER_MESSAGE,
    Reflection,
    TaggedMistake,
    UsedCorrectly,
    learner_message_ids,
    reflection_input,
    render_catalog,
    system_prompt,
    tagged_evidence,
)

IDS = {"u1": "msg-a", "u2": "msg-b"}
KC = "g.present_simple_third_person"


def mistake(message: str = "u1", kc_id: str = KC, original: str = "She like") -> TaggedMistake:
    return TaggedMistake(
        message=message,
        kc_id=kc_id,
        error_type="omission",
        severity="medium",
        original=original,
        correction="She likes",
    )


def test_learner_messages_get_short_ids_in_the_new_part() -> None:
    new = [HumanMessage("She like music", id="msg-a"), AIMessage("Nice!", id="ai-1"),
           HumanMessage("no id")]  # fmt: skip
    assert learner_message_ids(new) == {"u1": "msg-a"}
    text = reflection_input(
        profile=None, facts=[], earlier=[HumanMessage("Hi", id="old")], new=new, language="English"
    )
    assert "Learner [u1]: She like music" in text
    assert "Learner: Hi" in text  # earlier messages are context, never tagged
    assert "Tutor: Nice!" in text


def test_system_prompt_carries_the_whole_catalog() -> None:
    catalog = get_grammar_catalog()
    prompt = system_prompt()
    assert prompt.endswith(render_catalog(catalog))
    for kc in catalog.kcs:
        assert f"- {kc.id} ({kc.cefr}): " in prompt


def test_valid_mistakes_and_successes_are_kept() -> None:
    result = Reflection(
        mistakes=[mistake(), mistake("u2", "g.articles_basic", "I have car")],
        used_correctly=[UsedCorrectly(message="u2", kc_id="g.past_simple_irregular")],
    )
    items = tagged_evidence(result, IDS, get_grammar_catalog())
    assert [(i.message_id, i.kc_id, i.correct) for i in items] == [
        ("msg-a", KC, False),
        ("msg-b", "g.articles_basic", False),
        ("msg-b", "g.past_simple_irregular", True),
    ]
    assert items[0].severity == "medium" and items[0].correction == "She likes"
    assert items[2].severity is None and items[2].original is None


def test_unknown_ids_duplicates_and_empty_spans_are_dropped() -> None:
    result = Reflection(
        mistakes=[
            mistake(message="u9"),  # no such message
            mistake(kc_id="g.made_up"),  # not in the catalog
            mistake(original="   "),
            mistake(),
            mistake(original=" she LIKE "),  # same error again
        ],
        used_correctly=[
            UsedCorrectly(message="u1", kc_id=KC),  # also a mistake in u1
            UsedCorrectly(message="u1", kc_id="g.nope"),
        ],
    )
    items = tagged_evidence(result, IDS, get_grammar_catalog())
    assert [(i.message_id, i.kc_id, i.correct) for i in items] == [("msg-a", KC, False)]


def test_successes_are_capped_per_message() -> None:
    kcs = [kc.id for kc in get_grammar_catalog().kcs[: MAX_CORRECT_PER_MESSAGE + 2]]
    result = Reflection(used_correctly=[UsedCorrectly(message="u1", kc_id=k) for k in kcs])
    items = tagged_evidence(result, IDS, get_grammar_catalog())
    assert len(items) == MAX_CORRECT_PER_MESSAGE
