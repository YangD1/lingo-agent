import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.adaptive.kc.catalog import (
    CEFR_LEVELS,
    GrammarCatalog,
    KCCatalogError,
    load_grammar_catalog,
)


def kc(
    kc_id: str,
    cefr: str = "A1",
    prerequisites: list[str] | None = None,
    confusable_with: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": kc_id,
        "name_en": kc_id,
        "name_zh": kc_id,
        "cefr": cefr,
        "description": f"Uses {kc_id}.",
        "prerequisites": prerequisites or [],
        "confusable_with": confusable_with or [],
    }


def write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "grammar.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_loads_valid_catalog(tmp_path: Path) -> None:
    catalog = load_grammar_catalog(
        write(tmp_path, {"kcs": [kc("g.be"), kc("g.present_simple", prerequisites=["g.be"])]})
    )
    assert "g.present_simple" in catalog
    assert "g.missing" not in catalog
    found = catalog.get("g.present_simple")
    assert found is not None and found.prerequisites == ("g.be",)
    assert catalog.get("g.missing") is None


@pytest.mark.parametrize(
    ("kcs", "message"),
    [
        ([kc("g.be"), kc("g.be")], "duplicate KC id g.be"),
        ([kc("g.be", prerequisites=["g.be"])], "lists itself"),
        ([kc("g.be", prerequisites=["g.nope"])], "unknown prerequisite g.nope"),
        (
            [kc("g.easy", "A2", ["g.hard"]), kc("g.hard", "B1")],
            "requires g.hard at a higher level",
        ),
        (
            [kc("g.a", prerequisites=["g.c"]), kc("g.b", prerequisites=["g.a"]),
             kc("g.c", prerequisites=["g.b"])],
            "prerequisite cycle: g.a -> g.c -> g.b -> g.a",
        ),
        ([kc("g.a", confusable_with=["g.a"])], "lists itself as confusable"),
        ([kc("g.a", confusable_with=["g.nope"])], "unknown confusable g.nope"),
        ([kc("g.a", confusable_with=["g.b", "g.b"]), kc("g.b")], "listed as confusable twice"),
        # Owner is the lower level, then the smaller id; writing both sides trips this too.
        ([kc("g.a", "A2", confusable_with=["g.b"]), kc("g.b")], "pair with g.b under g.b"),
        ([kc("g.a", confusable_with=["g.b"]), kc("g.b", confusable_with=["g.a"])], "under g.a"),
        ([kc("g.a", confusable_with=["g.b"]), kc("g.b", "A2", ["g.a"])], "linked as prereq"),
        ([kc("g.a", confusable_with=["g.b"]), kc("g.b", "B2")], "too far apart"),
        (
            [kc("g.a", confusable_with=["g.b"]), kc("g.b", confusable_with=["g.c", "g.d", "g.e"]),
             kc("g.c"), kc("g.d"), kc("g.e")],
            "g.b has 4 confusable KCs",
        ),
    ],
)  # fmt: skip
def test_rejects_invalid_graph(tmp_path: Path, kcs: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(KCCatalogError, match=message):
        load_grammar_catalog(write(tmp_path, {"kcs": kcs}))


def test_confusables_are_symmetric(tmp_path: Path) -> None:
    kcs = [
        kc("g.past_simple", "A2", confusable_with=["g.present_perfect"]),
        kc("g.present_perfect", "B1", confusable_with=["g.used_to"]),
        kc("g.used_to", "B1"),
    ]
    catalog = load_grammar_catalog(write(tmp_path, {"kcs": kcs}))
    assert catalog.confusables("g.present_perfect") == ("g.past_simple", "g.used_to")
    assert catalog.confusables("g.used_to") == ("g.present_perfect",)
    assert catalog.confusables("g.nope") == ()
    assert catalog.confusable_pairs() == [
        ("g.past_simple", "g.present_perfect"),
        ("g.present_perfect", "g.used_to"),
    ]


@pytest.mark.parametrize(
    "patch",
    [
        {"id": "present_simple"},  # missing g. prefix
        {"id": "g.Present"},  # not snake_case
        {"cefr": "D1"},
        {"name_zh": ""},
        {"description": ""},
        {"extra": "field"},
    ],
)
def test_rejects_invalid_entry(tmp_path: Path, patch: dict[str, Any]) -> None:
    with pytest.raises(KCCatalogError, match="invalid grammar KC catalog"):
        load_grammar_catalog(write(tmp_path, {"kcs": [kc("g.be") | patch]}))


def test_rejects_empty_catalog(tmp_path: Path) -> None:
    with pytest.raises(KCCatalogError):
        load_grammar_catalog(write(tmp_path, {"kcs": []}))


def test_missing_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(KCCatalogError, match="not found"):
        load_grammar_catalog(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("kcs: [unclosed", encoding="utf-8")
    with pytest.raises(KCCatalogError, match="not valid YAML"):
        load_grammar_catalog(bad)


def test_shipped_catalog_is_valid() -> None:
    catalog = load_grammar_catalog()
    assert 80 <= len(catalog.kcs) <= 120
    # Every level has KCs, so placement can set priors across the whole range.
    assert {k.cefr for k in catalog.kcs} == set(CEFR_LEVELS)
    assert isinstance(catalog, GrammarCatalog)


def test_shipped_error_examples_have_one_owner() -> None:
    # A quoted learner sentence listed under two KCs would split its evidence.
    owners: dict[str, str] = {}
    for k in load_grammar_catalog().kcs:
        for hint in k.common_errors:
            for example in re.findall(r'"([^"]+)"', hint):
                assert owners.setdefault(example, k.id) == k.id, (example, owners[example], k.id)


def test_shipped_confusables() -> None:
    catalog = load_grammar_catalog()
    # Hand-reviewed pairs (task 45); a big jump means the "learners swap them" bar slipped.
    assert 15 <= len(catalog.confusable_pairs()) <= 70
    assert catalog.confusables("g.will_future") == ("g.going_to_future",)
