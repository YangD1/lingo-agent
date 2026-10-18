from pathlib import Path

import pytest

import app.skills as skills
from app.skills import SkillCatalogError, UnknownSkillError, load_skills, parse_skill


def write_skill(
    root: Path,
    directory: str,
    front: str,
    body: str = "General rules.",
    references: dict[str, str] | None = None,
) -> Path:
    path = root / directory
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")
    for part, text in (references or {}).items():
        (path / "references").mkdir(exist_ok=True)
        (path / "references" / f"{part}.md").write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_skill(
        tmp_path,
        "exercise-writing",
        "name: exercise-writing\ndescription: How to write practice items.",
        body="Write the full sentence first.",
        references={"cloze": "Lock the gap with a hint.\n", "choice4": "One option fits."},
    )
    write_skill(tmp_path, "explaining", "name: explaining\ndescription: How to explain.")
    (tmp_path / "__pycache__").mkdir()
    monkeypatch.setattr(skills, "get_skills", lambda: load_skills(tmp_path))
    return tmp_path


def test_parses_front_matter_body_and_references(root: Path) -> None:
    skill = skills.load_skill("exercise-writing")

    assert skill.description == "How to write practice items."
    assert skill.body == "Write the full sentence first."
    assert list(skill.references) == ["choice4", "cloze"]
    assert skills.load_reference("exercise-writing", "cloze") == "Lock the gap with a hint."


def test_index_lists_every_skill_by_name(root: Path) -> None:
    assert skills.skill_index() == [
        ("exercise-writing", "How to write practice items."),
        ("explaining", "How to explain."),
    ]


@pytest.mark.parametrize(
    "name",
    ["nope", "", "EXERCISE-WRITING", "../exercise-writing", "exercise-writing/SKILL.md", "/etc"],
)
def test_unknown_names_and_paths_are_refused(root: Path, name: str) -> None:
    with pytest.raises(UnknownSkillError):
        skills.load_skill(name)


@pytest.mark.parametrize("part", ["nope", "../SKILL", "cloze.md", "../../explaining/SKILL"])
def test_unknown_parts_and_paths_are_refused(root: Path, part: str) -> None:
    with pytest.raises(UnknownSkillError):
        skills.load_reference("exercise-writing", part)


@pytest.mark.parametrize(
    ("front", "body"),
    [
        ("name: broken", "Body."),  # no description
        ("description: No name.", "Body."),
        ("name: broken\ndescription: ''", "Body."),
        ("name: broken\ndescription: Fine.", ""),
        ("name: Broken_Name\ndescription: Fine.", "Body."),
        ("name: broken\ndescription: Fine.\nextra: 1", "Body."),
        ("- just\n- a list", "Body."),
        ("name: [unclosed", "Body."),
    ],
)
def test_badly_formed_skills_are_errors(tmp_path: Path, front: str, body: str) -> None:
    path = write_skill(tmp_path, "broken", front, body=body)
    with pytest.raises(SkillCatalogError):
        parse_skill(path)


def test_no_front_matter_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "broken"
    path.mkdir()
    (path / "SKILL.md").write_text("name: broken\n", encoding="utf-8")
    with pytest.raises(SkillCatalogError):
        parse_skill(path)


def test_name_must_match_its_directory(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "one", "name: other\ndescription: Fine.")
    with pytest.raises(SkillCatalogError, match="directory"):
        parse_skill(path)


def test_empty_reference_is_an_error(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path, "broken", "name: broken\ndescription: Fine.", references={"cloze": "  \n"}
    )
    with pytest.raises(SkillCatalogError):
        parse_skill(path)


def test_built_in_skills_load() -> None:
    for name, description in skills.skill_index():
        assert description
        assert skills.load_skill(name).body
