"""The placement grammar item bank (ADR 0010 §4, ADR 0012 §3, P1 plan §6.1).

`items.yaml` is reviewed content checked into the repo: four-option gap-fill items,
each testing one grammar KC. An item's prior difficulty is never written by hand; it is
computed from its per-dimension rubric ratings with `elo.prior_difficulty`, so tuning
the coefficients in `rules.yaml` re-prices the whole bank. Item ids are permanent:
answer statistics (task 15) hang off them.
"""

from functools import cache
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.adaptive.elo import prior_difficulty
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import Rules, get_rules

ITEMS_PATH = Path(__file__).parent / "items.yaml"
BLANK = "___"
_ID_PATTERN = r"^p\.[a-z][a-z0-9_]*\.[0-9]+$"

Text = Annotated[str, Field(min_length=1, max_length=300)]


class ItemBankError(Exception):
    """The item bank file is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rating(_Strict):
    """One rubric dimension: the chosen level and why, kept for review and re-tuning."""

    level: str
    reason: Text


class RawItem(_Strict):
    id: str = Field(pattern=_ID_PATTERN)
    kc: str
    # Exactly one BLANK; may contain a newline for a two-line exchange.
    stem: Text
    answer: Text
    distractors: tuple[Text, Text, Text]
    rubric: dict[str, Rating]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.stem.count(BLANK) != 1:
            raise ValueError(f"{self.id}: stem must contain exactly one {BLANK}")
        options = [self.answer, *self.distractors]
        if len({o.strip().casefold() for o in options}) != len(options):
            raise ValueError(f"{self.id}: options must be distinct")
        return self


class RawBank(_Strict):
    format: str
    items: tuple[RawItem, ...] = Field(min_length=1)


class Item(_Strict):
    id: str
    kc: str
    cefr: CefrLevel
    stem: str
    answer: str
    distractors: tuple[str, str, str]
    ratings: dict[str, str]
    difficulty: float

    @property
    def options(self) -> tuple[str, str, str, str]:
        """Answer first; callers shuffle before showing."""
        return (self.answer, *self.distractors)


class ItemBank(_Strict):
    format: str
    items: tuple[Item, ...]

    def get(self, item_id: str) -> Item | None:
        return next((item for item in self.items if item.id == item_id), None)


def build_bank(raw: RawBank, catalog: GrammarCatalog, rules: Rules) -> ItemBank:
    """Check references against the KC catalog and rules, and price each item."""
    if raw.format not in rules.elo.guess_by_format:
        raise ValueError(f"format {raw.format!r} has no guess rate in rules.elo.guess_by_format")
    seen_ids: set[str] = set()
    seen_stems: set[str] = set()
    items: list[Item] = []
    for r in raw.items:
        if r.id in seen_ids:
            raise ValueError(f"duplicate item id {r.id}")
        seen_ids.add(r.id)
        stem_key = " ".join(r.stem.casefold().split())
        if stem_key in seen_stems:
            raise ValueError(f"{r.id}: duplicate stem")
        seen_stems.add(stem_key)
        kc = catalog.get(r.kc)
        if kc is None:
            raise ValueError(f"{r.id}: unknown KC {r.kc}")
        if not r.id.startswith(f"p.{r.kc.removeprefix('g.')}."):
            raise ValueError(f"{r.id}: id must be p.<kc name>.<n>")
        ratings = {name: rating.level for name, rating in r.rubric.items()}
        try:
            difficulty = prior_difficulty(kc.cefr, ratings, rules)
        except ValueError as exc:
            raise ValueError(f"{r.id}: {exc}") from exc
        items.append(
            Item(
                id=r.id,
                kc=r.kc,
                cefr=kc.cefr,
                stem=r.stem,
                answer=r.answer,
                distractors=r.distractors,
                ratings=ratings,
                difficulty=difficulty,
            )
        )
    return ItemBank(format=raw.format, items=tuple(items))


def load_item_bank(
    path: Path = ITEMS_PATH,
    catalog: GrammarCatalog | None = None,
    rules: Rules | None = None,
) -> ItemBank:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ItemBankError(f"placement item bank not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ItemBankError(f"placement item bank {path} is not valid YAML: {exc}") from exc
    try:
        raw = RawBank.model_validate(data)
        return build_bank(raw, catalog or get_grammar_catalog(), rules or get_rules())
    except (ValidationError, ValueError) as exc:
        raise ItemBankError(f"invalid placement item bank {path}:\n{exc}") from exc


@cache
def get_item_bank() -> ItemBank:
    return load_item_bank()
