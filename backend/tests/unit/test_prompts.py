import re

from app.prompts import load_prompt, prompt_names, prompt_version, prompt_versions


def test_version_is_a_hash_of_the_text() -> None:
    assert re.fullmatch(r"[0-9a-f]{8}", prompt_version("route"))
    assert prompt_version("route") != prompt_version("translate")


def test_every_prompt_is_recognised_with_its_placeholders_filled() -> None:
    for name in prompt_names():
        filled = re.sub(r"\{[a-z_]+\}", "Learner said: I goed home.", load_prompt(name))
        found = prompt_versions(f"Before.\n\n{filled}\n\nAfter.") or {}
        # Only itself: no prompt's fingerprint sits inside another prompt.
        assert found == {name: prompt_version(name)}, name


def test_text_without_a_prompt_is_none() -> None:
    assert prompt_versions("I goed to school yesterday.") is None
    assert prompt_versions("") is None


def test_a_prompt_cut_short_is_not_claimed() -> None:
    text = load_prompt("reflect")
    assert prompt_versions(text[: len(text) // 2]) is None
