"""The grammar KC catalog: stable ids the whole learner model hangs off (ADR 0010 §1).

`grammar.yaml` is hand-reviewed content checked into the repo. Its ids are referenced by
`kc_mastery`, `mistakes`, the placement item bank and (P2) the grammar graph in
`kc_edges` (ADR 0022), so an id is never renamed once shipped. The file is validated at
startup: a broken catalog would otherwise surface as reflection silently dropping every
tagged mistake.
"""

from functools import cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
CEFR_LEVELS: tuple[CefrLevel, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
# How a learner's sentence deviates from the target form. Deliberately coarse and
# global (not per KC) so mistakes stay countable across KCs; the per-KC
# `common_errors` below are only hints for the model that tags them.
ErrorType = Literal["omission", "addition", "wrong_form", "wrong_choice", "word_order"]
ERROR_TYPES: tuple[ErrorType, ...] = (
    "omission",
    "addition",
    "wrong_form",
    "wrong_choice",
    "word_order",
)

GRAMMAR_CATALOG_PATH = Path(__file__).parent / "grammar.yaml"
# Confusable pairs are few and hand-reviewed (Q45a-b): more than this per KC means the
# relation has drifted from "learners swap one for the other" to "same chapter".
MAX_CONFUSABLES = 3
# Learners confuse forms they meet at nearby levels; a wider gap is a prerequisite or nothing.
MAX_CONFUSABLE_LEVEL_GAP = 2
_ID_PATTERN = r"^g\.[a-z][a-z0-9_]*$"


class KCCatalogError(Exception):
    """The KC catalog file is missing or invalid."""


class GrammarKC(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID_PATTERN)
    name_en: str = Field(min_length=1)
    name_zh: str = Field(min_length=1)
    cefr: CefrLevel
    # One English sentence, shown to the reflection model next to the id.
    description: str = Field(min_length=1)
    prerequisites: tuple[str, ...] = ()
    # KCs learners use in place of this one (ADR 0022). Each pair is written once, under
    # its owner (see `_confusable_owner`); the catalog makes it symmetric.
    confusable_with: tuple[str, ...] = ()
    common_errors: tuple[str, ...] = ()


class GrammarCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kcs: tuple[GrammarKC, ...] = Field(min_length=1)
    _by_id: dict[str, GrammarKC] = PrivateAttr(default_factory=dict)
    _confusables: dict[str, tuple[str, ...]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        by_id: dict[str, GrammarKC] = {}
        for kc in self.kcs:
            if kc.id in by_id:
                raise ValueError(f"duplicate KC id {kc.id}")
            by_id[kc.id] = kc
        for kc in self.kcs:
            for pre in kc.prerequisites:
                if pre == kc.id:
                    raise ValueError(f"{kc.id} lists itself as a prerequisite")
                if pre not in by_id:
                    raise ValueError(f"{kc.id}: unknown prerequisite {pre}")
                if _rank(by_id[pre].cefr) > _rank(kc.cefr):
                    raise ValueError(
                        f"{kc.id} ({kc.cefr}) requires {pre} at a higher level ({by_id[pre].cefr})"
                    )
        if cycle := _find_cycle(by_id):
            raise ValueError("prerequisite cycle: " + " -> ".join(cycle))
        self._by_id = by_id
        self._confusables = _check_confusables(by_id)
        return self

    def __contains__(self, kc_id: object) -> bool:
        return kc_id in self._by_id

    def get(self, kc_id: str) -> GrammarKC | None:
        return self._by_id.get(kc_id)

    def confusables(self, kc_id: str) -> tuple[str, ...]:
        """KCs confusable with `kc_id`, in both directions, sorted by id."""
        return self._confusables.get(kc_id, ())

    def confusable_pairs(self) -> list[tuple[str, str]]:
        """Each confusable pair once, as (owner, other) in catalog order."""
        return [(kc.id, other) for kc in self.kcs for other in kc.confusable_with]


def _rank(level: CefrLevel) -> int:
    return CEFR_LEVELS.index(level)


def _confusable_owner(a: GrammarKC, b: GrammarKC) -> GrammarKC:
    """The KC a pair is written under: the lower level, then the smaller id."""
    return min(a, b, key=lambda kc: (_rank(kc.cefr), kc.id))


def _check_confusables(by_id: dict[str, GrammarKC]) -> dict[str, tuple[str, ...]]:
    linked: dict[str, set[str]] = {}
    for kc in by_id.values():
        for other_id in kc.confusable_with:
            if other_id == kc.id:
                raise ValueError(f"{kc.id} lists itself as confusable")
            other = by_id.get(other_id)
            if other is None:
                raise ValueError(f"{kc.id}: unknown confusable {other_id}")
            owner = _confusable_owner(kc, other)
            if owner is not kc:
                raise ValueError(
                    f"{kc.id}: write the confusable pair with {other_id} under {owner.id}"
                )
            if other_id in linked.get(kc.id, ()):
                raise ValueError(f"{kc.id} and {other_id} are listed as confusable twice")
            if other_id in kc.prerequisites or kc.id in other.prerequisites:
                raise ValueError(f"{kc.id} and {other_id} are already linked as prerequisites")
            if abs(_rank(kc.cefr) - _rank(other.cefr)) > MAX_CONFUSABLE_LEVEL_GAP:
                raise ValueError(
                    f"{kc.id} ({kc.cefr}) and {other_id} ({other.cefr}) are too far apart "
                    "to be confusable"
                )
            linked.setdefault(kc.id, set()).add(other_id)
            linked.setdefault(other_id, set()).add(kc.id)
    for kc_id, others in linked.items():
        if len(others) > MAX_CONFUSABLES:
            raise ValueError(
                f"{kc_id} has {len(others)} confusable KCs (at most {MAX_CONFUSABLES})"
            )
    return {kc_id: tuple(sorted(others)) for kc_id, others in linked.items()}


def _find_cycle(by_id: dict[str, GrammarKC]) -> list[str] | None:
    """Return one prerequisite cycle as a closed path, or None if the graph is a DAG."""
    done: set[str] = set()
    path: list[str] = []
    on_path: set[str] = set()

    def visit(kc_id: str) -> list[str] | None:
        if kc_id in on_path:
            return [*path[path.index(kc_id) :], kc_id]
        if kc_id in done:
            return None
        path.append(kc_id)
        on_path.add(kc_id)
        for pre in by_id[kc_id].prerequisites:
            if cycle := visit(pre):
                return cycle
        path.pop()
        on_path.discard(kc_id)
        done.add(kc_id)
        return None

    for kc_id in by_id:
        if cycle := visit(kc_id):
            return cycle
    return None


def load_grammar_catalog(path: Path = GRAMMAR_CATALOG_PATH) -> GrammarCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KCCatalogError(f"grammar KC catalog not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise KCCatalogError(f"grammar KC catalog {path} is not valid YAML: {exc}") from exc
    try:
        return GrammarCatalog.model_validate(raw)
    except ValidationError as exc:
        raise KCCatalogError(f"invalid grammar KC catalog {path}:\n{exc}") from exc


@cache
def get_grammar_catalog() -> GrammarCatalog:
    return load_grammar_catalog()
