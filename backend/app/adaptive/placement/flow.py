"""The placement test's questions, answers and result, as pure functions (P1 plan §6.2).

The placement graph keeps a `Progress` (the seed and the answers so far) in its
checkpoint and calls these. Every question is recomputed from the progress: the n-th
question of a stage draws from `Random(f"{seed}:{stage}:{n}")`, so a test resumed
after the page was closed, or a graph step re-run, asks the same question again.

Two stages: yes/no vocabulary questions (real words by frequency band, pseudo-words at
fixed shuffled positions), then four-option grammar items. Only the grammar level
places the learner (Q15d); the vocabulary part gives a size and a reference level.
"""

import random
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.placement import grammar_test, vocab_size
from app.adaptive.placement.grammar_test import GrammarAnswer
from app.adaptive.placement.items import ItemBank
from app.adaptive.placement.pseudowords import get_pseudowords
from app.adaptive.placement.vocab_size import Answer
from app.adaptive.placement.words import WordPool
from app.adaptive.rules import PlacementVocabRules, Rules

type Stage = Literal["vocab", "grammar"]


class VocabRecord(TypedDict):
    word: str
    word_id: int | None  # None: a pseudo-word
    rank: int | None
    yes: bool


class GrammarRecord(TypedDict):
    item_id: str
    choice: str  # the option picked
    correct: bool


class Progress(TypedDict):
    seed: int
    # Item difficulties re-estimated from earlier tests, fixed when this test starts.
    difficulties: dict[str, float]
    vocab: list[VocabRecord]
    grammar: list[GrammarRecord]


class Question(TypedDict):
    """A question as kept in the checkpoint; `public` is what the learner sees."""

    id: str  # "vocab-3", "grammar-0": the stage and its 0-based index
    stage: Stage
    index: int
    total: int
    # vocab
    word: NotRequired[str]
    word_id: NotRequired[int | None]
    rank: NotRequired[int | None]
    # grammar
    item_id: NotRequired[str]
    stem: NotRequired[str]
    options: NotRequired[list[str]]


class AnswerInput(TypedDict):
    question_id: str
    yes: NotRequired[bool]  # vocab: "I know this word"
    choice: NotRequired[int]  # grammar: index into the options shown


class InvalidAnswerError(ValueError):
    """The answer does not fit the question it names."""


def new_progress(seed: int, difficulties: Mapping[str, float] | None = None) -> Progress:
    return {"seed": seed, "difficulties": dict(difficulties or {}), "vocab": [], "grammar": []}


def calibrated(bank: ItemBank, difficulties: Mapping[str, float]) -> ItemBank:
    """The bank with re-estimated difficulties where there are any."""
    if not difficulties:
        return bank
    items = tuple(
        item.model_copy(update={"difficulty": difficulties[item.id]})
        if item.id in difficulties
        else item
        for item in bank.items
    )
    return bank.model_copy(update={"items": items})


def _rng(progress: Progress, stage: Stage, index: int) -> random.Random:
    return random.Random(f"{progress['seed']}:{stage}:{index}")


def vocab_answers(progress: Progress) -> list[Answer]:
    return [Answer(rank=r["rank"], yes=r["yes"]) for r in progress["vocab"]]


def grammar_answers(progress: Progress) -> list[GrammarAnswer]:
    return [GrammarAnswer(item_id=r["item_id"], correct=r["correct"]) for r in progress["grammar"]]


def _vocab_question(
    progress: Progress, pool: WordPool, rules: PlacementVocabRules
) -> Question | None:
    done = progress["vocab"]
    index = len(done)
    if index >= rules.questions:
        return None
    plan = vocab_size.schedule(rules, random.Random(f"{progress['seed']}:schedule"))
    rng = _rng(progress, "vocab", index)
    base: Question = {
        "id": f"vocab-{index}",
        "stage": "vocab",
        "index": index,
        "total": rules.questions,
    }
    if plan[index]:
        shown = {r["word"] for r in done}
        left = [w for w in get_pseudowords() if w not in shown]
        if left:
            return {**base, "word": rng.choice(left), "word_id": None, "rank": None}
    used = {r["word_id"] for r in done if r["word_id"] is not None}
    order = vocab_size.bands_by_distance(vocab_answers(progress), rules)
    word = pool.pick_nearest(order, used, rng)
    if word is None:
        return None  # the pool ran out: end the stage early
    return {**base, "word": word.word, "word_id": word.id, "rank": word.rank}


def _grammar_question(progress: Progress, bank: ItemBank, rules: Rules) -> Question | None:
    answers = grammar_answers(progress)
    if grammar_test.finished(answers, bank, rules):
        return None
    index = len(answers)
    rng = _rng(progress, "grammar", index)
    item = grammar_test.pick_item(answers, bank, rules, rng)
    if item is None:
        return None
    return {
        "id": f"grammar-{index}",
        "stage": "grammar",
        "index": index,
        "total": rules.placement.grammar.max_items,
        "item_id": item.id,
        "stem": item.stem,
        "options": rng.sample(list(item.options), k=len(item.options)),
    }


def next_question(
    progress: Progress, pool: WordPool, bank: ItemBank, rules: Rules
) -> Question | None:
    """The question to ask now, or None when the test is over."""
    if not progress["grammar"]:
        question = _vocab_question(progress, pool, rules.placement.vocab)
        if question is not None:
            return question
    return _grammar_question(progress, calibrated(bank, progress["difficulties"]), rules)


def record(progress: Progress, question: Question, answer: AnswerInput, bank: ItemBank) -> Progress:
    """Progress with the answer to `question` added; raises InvalidAnswerError."""
    if answer.get("question_id") != question["id"]:
        raise InvalidAnswerError("answer is for another question")
    if question["stage"] == "vocab":
        yes = answer.get("yes")
        if not isinstance(yes, bool):
            raise InvalidAnswerError("a vocabulary answer needs yes")
        entry: VocabRecord = {
            "word": question["word"],
            "word_id": question["word_id"],
            "rank": question["rank"],
            "yes": yes,
        }
        return {**progress, "vocab": [*progress["vocab"], entry]}
    options = question["options"]
    choice = answer.get("choice")
    if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice < len(options):
        raise InvalidAnswerError("a grammar answer needs the index of an option")
    item = bank.get(question["item_id"])
    if item is None:
        raise InvalidAnswerError("unknown item")
    picked = options[choice]
    grammar: GrammarRecord = {
        "item_id": item.id,
        "choice": picked,
        "correct": picked == item.answer,
    }
    return {**progress, "grammar": [*progress["grammar"], grammar]}


def public(question: Question) -> dict[str, object]:
    """What the learner sees: nothing that tells a pseudo-word, a rank or the item's KC."""
    shown: dict[str, object] = {
        "id": question["id"],
        "stage": question["stage"],
        "index": question["index"],
        "total": question["total"],
    }
    if question["stage"] == "vocab":
        shown["word"] = question["word"]
    else:
        shown["stem"] = question["stem"]
        shown["options"] = question["options"]
    return shown


# --- result ---------------------------------------------------------------------------


def vocab_reference(half_known_rank: float, rules: PlacementVocabRules) -> CefrLevel | None:
    """Rough CEFR level from the number of known words among the most frequent ranks."""
    ref = rules.cefr_reference
    if ref is None:
        return None
    counted = vocab_size.bands(rules)[: ref.basis // rules.band_size]
    known = sum(
        rules.band_size * vocab_size.p_know(half_known_rank, b.middle, rules) for b in counted
    )
    level: CefrLevel = CEFR_LEVELS[0]
    for candidate in CEFR_LEVELS[1:]:
        if known >= ref.thresholds[candidate]:
            level = candidate
    return level


class VocabResult(TypedDict):
    size: int
    half_known_rank: int
    false_alarm: float
    reliable: bool
    reference_cefr: CefrLevel | None
    answered: int


class GrammarResultDict(TypedDict):
    ability: float
    standard_error: float
    cefr: CefrLevel
    answered: int


class Answers(TypedDict):
    vocab: list[VocabRecord]
    grammar: list[GrammarRecord]


class PlacementResult(TypedDict):
    cefr: CefrLevel  # overall: the grammar level (Q15d)
    vocab: VocabResult
    grammar: GrammarResultDict
    # The answers, kept for re-estimating item difficulties and for the record.
    answers: Answers


def summarize(progress: Progress, pool: WordPool, bank: ItemBank, rules: Rules) -> PlacementResult:
    vr = rules.placement.vocab
    v = vocab_size.estimate(vocab_answers(progress), vr, pool.band_words)
    g = grammar_test.result(
        grammar_answers(progress), calibrated(bank, progress["difficulties"]), rules
    )
    return {
        "cefr": g.cefr,
        "vocab": {
            "size": v.size,
            "half_known_rank": v.half_known_rank,
            "false_alarm": round(v.false_alarm, 3),
            "reliable": v.reliable,
            "reference_cefr": vocab_reference(v.half_known_rank, vr),
            "answered": len(progress["vocab"]),
        },
        "grammar": {
            "ability": round(g.ability, 3),
            "standard_error": round(g.standard_error, 3),
            "cefr": g.cefr,
            "answered": g.answered,
        },
        "answers": {"vocab": progress["vocab"], "grammar": progress["grammar"]},
    }
