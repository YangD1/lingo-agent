import pytest

from app.adaptive.placement import flow
from app.adaptive.placement.flow import AnswerInput, InvalidAnswerError, Progress, Question
from app.adaptive.placement.items import ItemBank, get_item_bank
from app.adaptive.placement.pseudowords import get_pseudowords
from app.adaptive.placement.words import WordPool, build_pool
from app.adaptive.rules import Rules, get_rules
from tests.unit.placement_fixtures import POOL

RULES = get_rules()
BANK = get_item_bank()


def answer_for(question: Question, *, knows_up_to: int, correct: bool) -> AnswerInput:
    if question["stage"] == "vocab":
        rank = question["rank"]
        return {"question_id": question["id"], "yes": rank is not None and rank <= knows_up_to}
    item = BANK.get(question["item_id"])
    assert item is not None
    options = question["options"]
    wanted = item.answer if correct else item.distractors[0]
    return {"question_id": question["id"], "choice": options.index(wanted)}


def run(
    seed: int,
    *,
    knows_up_to: int = 4000,
    pool: WordPool = POOL,
    bank: ItemBank = BANK,
    rules: Rules = RULES,
) -> tuple[Progress, list[Question]]:
    progress = flow.new_progress(seed)
    asked: list[Question] = []
    while (question := flow.next_question(progress, pool, bank, rules)) is not None:
        asked.append(question)
        correct = question["index"] % 3 != 0
        progress = flow.record(
            progress, question, answer_for(question, knows_up_to=knows_up_to, correct=correct), bank
        )
        assert len(asked) < 200
    return progress, asked


def test_a_whole_test_runs_vocab_then_grammar() -> None:
    progress, asked = run(seed=1)
    vr = RULES.placement.vocab
    stages = [q["stage"] for q in asked]
    assert stages == ["vocab"] * vr.questions + ["grammar"] * len(progress["grammar"])
    assert 1 <= len(progress["grammar"]) <= RULES.placement.grammar.max_items
    pseudo = [r for r in progress["vocab"] if r["word_id"] is None]
    assert len(pseudo) == round(vr.questions * vr.pseudo_share)
    assert all(r["word"] in get_pseudowords() for r in pseudo)
    words = [r["word"] for r in progress["vocab"]]
    assert len(set(words)) == len(words)
    items = [r["item_id"] for r in progress["grammar"]]
    assert len(set(items)) == len(items)


def test_the_same_seed_and_answers_ask_the_same_questions() -> None:
    _, first = run(seed=7)
    _, again = run(seed=7)
    _, other = run(seed=8)
    assert first == again
    assert first != other


def test_questions_are_recomputed_from_progress() -> None:
    progress, asked = run(seed=3)
    # Replaying any prefix of the answers gives the question that followed it.
    for n in (0, 5, 40, 45):
        prefix: Progress = {
            **progress,
            "vocab": progress["vocab"][:n],
            "grammar": progress["grammar"][: max(0, n - 40)],
        }
        assert flow.next_question(prefix, POOL, BANK, RULES) == asked[n]


def test_options_are_shuffled_and_hold_the_answer() -> None:
    _, asked = run(seed=5)
    grammar = [q for q in asked if q["stage"] == "grammar"]
    firsts = set()
    for q in grammar:
        item = BANK.get(q["item_id"])
        assert item is not None
        assert sorted(q["options"]) == sorted(item.options)
        firsts.add(q["options"].index(item.answer))
    assert len(firsts) > 1


def test_public_view_hides_what_would_give_answers_away() -> None:
    _, asked = run(seed=2)
    for q in asked:
        shown = flow.public(q)
        assert set(shown) <= {"id", "stage", "index", "total", "word", "stem", "options"}
    vocab = flow.public(asked[0])
    assert "word" in vocab and "rank" not in vocab and "word_id" not in vocab


def test_an_exhausted_pool_ends_the_vocab_stage_early() -> None:
    small = build_pool([(1, "cat", 5, None), (2, "dog", 1500, None)], RULES.placement.vocab)
    progress, asked = run(seed=4, pool=small)
    assert 2 <= len(progress["vocab"]) < RULES.placement.vocab.questions
    assert asked[-1]["stage"] == "grammar"


def test_record_rejects_answers_that_do_not_fit() -> None:
    progress = flow.new_progress(1)
    vocab = flow.next_question(progress, POOL, BANK, RULES)
    assert vocab is not None
    bad: list[AnswerInput] = [
        {"question_id": "vocab-9", "yes": True},
        {"question_id": vocab["id"]},
        {"question_id": vocab["id"], "choice": 1},
    ]
    for answer in bad:
        with pytest.raises(InvalidAnswerError):
            flow.record(progress, vocab, answer, BANK)
    grammar, _ = run(seed=1)
    grammar = {**grammar, "grammar": []}
    question = flow.next_question(grammar, POOL, BANK, RULES)
    assert question is not None and question["stage"] == "grammar"
    for choice in (-1, 4, True):
        with pytest.raises(InvalidAnswerError):
            flow.record(grammar, question, {"question_id": question["id"], "choice": choice}, BANK)


def test_calibrated_difficulties_replace_the_prior() -> None:
    item = BANK.items[0]
    bank = flow.calibrated(BANK, {item.id: 5.0})
    assert bank.get(item.id).difficulty == 5.0  # type: ignore[union-attr]
    assert bank.items[1] == BANK.items[1]
    assert flow.calibrated(BANK, {}) is BANK


def test_vocab_reference_level_rises_with_vocabulary() -> None:
    vr = RULES.placement.vocab
    levels = [flow.vocab_reference(v, vr) for v in (300, 1500, 2600, 3600, 5000, 12000)]
    assert levels[0] == "A1"
    assert levels[-1] == "C2"
    order = ["A1", "A2", "B1", "B2", "C1", "C2"]
    assert [order.index(lv) for lv in levels] == sorted(order.index(lv) for lv in levels)  # type: ignore[arg-type]


def test_summarize() -> None:
    progress, _ = run(seed=6, knows_up_to=6000)
    result = flow.summarize(progress, POOL, BANK, RULES)
    assert result["cefr"] == result["grammar"]["cefr"]
    assert result["grammar"]["answered"] == len(progress["grammar"])
    assert result["vocab"]["answered"] == RULES.placement.vocab.questions
    # Counts the pool's words (30 a band), not every rank.
    assert 0 < result["vocab"]["size"] <= 30 * 20
    assert result["vocab"]["reliable"]
    assert result["answers"]["grammar"] == progress["grammar"]
