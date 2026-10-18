"""`make prompts`: each prompt's and skill part's name, version and length (ADR 0033 §1)."""

import hashlib

from app.prompts import prompt_texts


def main() -> None:
    for name, text in prompt_texts():
        lines = text.count("\n") + 1
        version = hashlib.sha256(text.encode()).hexdigest()[:8]
        print(f"{name:<40} {version}  {lines:>3} lines")


if __name__ == "__main__":
    main()
