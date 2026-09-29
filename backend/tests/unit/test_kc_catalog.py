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


def kc(kc_id: str, cefr: str = "A1", prerequisites: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": kc_id,
        "name_en": kc_id,
        "name_zh": kc_id,
        "cefr": cefr,
        "description": f"Uses {kc_id}.",
        "prerequisites": prerequisites or [],
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
    ],
)  # fmt: skip
def test_rejects_invalid_graph(tmp_path: Path, kcs: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(KCCatalogError, match=message):
        load_grammar_catalog(write(tmp_path, {"kcs": kcs}))


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
