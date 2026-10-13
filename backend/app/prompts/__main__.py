"""`make prompts`: each prompt's name, version and length (ADR 0033 §1)."""

from app.prompts import load_prompt, prompt_names, prompt_version


def main() -> None:
    for name in prompt_names():
        lines = load_prompt(name).count("\n") + 1
        print(f"{name:<24} {prompt_version(name)}  {lines:>3} lines")


if __name__ == "__main__":
    main()
