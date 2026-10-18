import re

from app.prompts import load_prompt, prompt_texts, prompt_version, prompt_versions


def test_version_is_a_hash_of_the_text() -> None:
    assert re.fullmatch(r"[0-9a-f]{8}", prompt_version("route"))
    assert prompt_version("route") != prompt_version("translate")


def test_every_prompt_and_skill_part_is_recognised_with_its_placeholders_filled() -> None:
    versions = dict(prompt_versions("\n\n".join(text for _, text in prompt_texts())) or {})
    names = [name for name, _ in prompt_texts()]
    assert any(name.startswith("skill:exercise-writing/") for name in names)
    for name, text in prompt_texts():
        filled = re.sub(r"\{[a-z_]+\}", "Learner said: I goed home.", text)
        found = prompt_versions(f"Before.\n\n{filled}\n\nAfter.") or {}
        # Only itself: no prompt's fingerprint sits inside another prompt.
        assert found == {name: versions[name]}, name


def test_text_without_a_prompt_is_none() -> None:
    assert prompt_versions("I goed to school yesterday.") is None
    assert prompt_versions("") is None


def test_a_prompt_cut_short_is_not_claimed() -> None:
    text = load_prompt("reflect")
    assert prompt_versions(text[: len(text) // 2]) is None
