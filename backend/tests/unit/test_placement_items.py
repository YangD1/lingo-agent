from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.adaptive.kc.catalog import CEFR_LEVELS, get_grammar_catalog
from app.adaptive.placement.items import BLANK, ItemBankError, get_item_bank, load_item_bank
from app.adaptive.rules import get_rules

RUBRIC = {
    "vocabulary": "at_target",
    "syntax": "simple",
    "cues": "partial",
    "distractors": "one_plausible",
}


def item(item_id: str = "p.be_present.1", kc: str = "g.be_present", **overrides: Any) -> Any:
    data = {
        "id": item_id,
        "kc": kc,
        "stem": "They ___ happy.",
        "answer": "are",
        "distractors": ["is", "am", "be"],
        "rubric": {name: {"level": level, "reason": "r"} for name, level in RUBRIC.items()},
    }
    return data | overrides


def write(tmp_path: Path, items: list[Any], fmt: str = "choice4") -> Path:
    path = tmp_path / "items.yaml"
    path.write_text(yaml.safe_dump({"format": fmt, "items": items}), encoding="utf-8")
    return path


def test_prices_items_from_rubric(tmp_path: Path) -> None:
    bank = load_item_bank(write(tmp_path, [item()]))
    found = bank.get("p.be_present.1")
    assert found is not None
    rules = get_rules()
    # A1 anchor + at_target 0 + simple + partial 0 + one_plausible 0
    simple = rules.difficulty.dimensions["syntax"].levels["simple"].offset
    assert found.difficulty == pytest.approx(rules.difficulty.cefr_anchor["A1"] + simple)
    assert found.cefr == "A1"
    assert found.options == ("are", "is", "am", "be")
    assert bank.get("p.missing.1") is None


@pytest.mark.parametrize(
    ("items", "fmt", "message"),
    [
        ([item(stem="They are happy.")], "choice4", "exactly one ___"),
        ([item(stem="___ are ___.")], "choice4", "exactly one ___"),
        ([item(distractors=["is", "Are ", "be"])], "choice4", "options must be distinct"),
        ([item(distractors=["is", "am"])], "choice4", "distractors"),
        ([item(), item()], "choice4", "duplicate item id"),
        ([item(), item("p.be_present.2")], "choice4", "duplicate stem"),
        ([item("p.nope.1", "g.nope")], "choice4", "unknown KC g.nope"),
        ([item("p.articles_basic.1")], "choice4", "id must be p.<kc name>.<n>"),
        ([item("be_present.1")], "choice4", "String should match pattern"),
        ([item()], "choice9", "no guess rate"),
        ([item(rubric={"syntax": {"level": "simple", "reason": "r"}})], "choice4", "missing"),
        (
            [item(rubric={n: {"level": "huge", "reason": "r"} for n in RUBRIC})],
            "choice4",
            "unknown level 'huge'",
        ),
        ([item(extra=1)], "choice4", "Extra inputs"),
    ],
)
def test_rejects_invalid_bank(tmp_path: Path, items: list[Any], fmt: str, message: str) -> None:
    with pytest.raises(ItemBankError, match=message.replace("(", r"\(").replace(".", r"\.")):
        load_item_bank(write(tmp_path, items, fmt))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ItemBankError, match="not found"):
        load_item_bank(tmp_path / "nope.yaml")


# ---------------------------------------------------------------- the shipped bank


def test_shipped_bank_loads() -> None:
    bank = get_item_bank()
    assert 80 <= len(bank.items) <= 100


def test_shipped_bank_covers_every_level() -> None:
    per_level = Counter(i.cefr for i in get_item_bank().items)
    assert set(per_level) == set(CEFR_LEVELS)
    assert all(per_level[level] >= 5 for level in CEFR_LEVELS)


def test_shipped_bank_spreads_over_kcs() -> None:
    per_kc = Counter(i.kc for i in get_item_bank().items)
    assert max(per_kc.values()) <= 2


def test_shipped_bank_difficulty_rises_with_level() -> None:
    items = get_item_bank().items
    medians = []
    for level in CEFR_LEVELS:
        values = sorted(i.difficulty for i in items if i.cefr == level)
        medians.append(values[len(values) // 2])
    assert medians == sorted(medians)


def test_shipped_bank_answers_fit_the_gap() -> None:
    """No option repeats a word already standing next to the gap ("to ___ to go")."""
    for i in get_item_bank().items:
        before, after = i.stem.split(BLANK)
        last_before = before.split()[-1:] or [""]
        first_after = after.split()[:1] or [""]
        for option in i.options:
            words = option.split()
            assert words[0].casefold() != last_before[0].casefold(), i.id
            assert words[-1].casefold() != first_after[0].strip(".,?!").casefold(), i.id


def test_shipped_bank_kcs_exist() -> None:
    catalog = get_grammar_catalog()
    assert all(i.kc in catalog for i in get_item_bank().items)
