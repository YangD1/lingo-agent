"""Markdown in a reading document (task 84): blocks keep their structure."""

from app.workspace.markdown import blocks_of, contains, is_code, plain

ARTICLE = """# Street trees

Cities are planting
more trees.

## Why it matters
Trees give **shade** and make the air [cleaner](https://example.com).

- Shade on hot days
- Cleaner air
  - a little
1. Water them
2. Check them

> Planting is cheap,
> looking after it is not.

| City | Trees |
| --- | ---: |
| Paris | 100 |

```python
x = 1

print(x)
```

The end.
"""


def test_blocks_keep_their_markdown() -> None:
    assert blocks_of(ARTICLE) == [
        "# Street trees",
        # Prose lines join.
        "Cities are planting more trees.",
        # A heading stands alone even with no blank line after it.
        "## Why it matters",
        "Trees give **shade** and make the air [cleaner](https://example.com).",
        # Lists, quotes and tables keep their lines (and nesting).
        "- Shade on hot days\n- Cleaner air\n  - a little\n1. Water them\n2. Check them",
        "> Planting is cheap,\n> looking after it is not.",
        "| City | Trees |\n| --- | ---: |\n| Paris | 100 |",
        # A code block runs to its fence, blank line and all.
        "```python\nx = 1\n\nprint(x)\n```",
        "The end.",
    ]


def test_plain_text_has_no_marks() -> None:
    blocks = blocks_of(ARTICLE)
    assert plain(blocks[0]) == "Street trees"
    assert plain(blocks[3]) == "Trees give shade and make the air cleaner."
    assert plain(blocks[4]) == "Shade on hot days Cleaner air a little Water them Check them"
    assert plain(blocks[5]) == "Planting is cheap, looking after it is not."
    assert plain(blocks[6]) == "City Trees Paris 100"
    assert plain(blocks[7]) == ""
    # Underscores and asterisks inside words are not emphasis.
    assert plain("snake_case and 2*3*4 stay, *this* and _that_ don't") == (
        "snake_case and 2*3*4 stay, this and that don't"
    )


def test_code_blocks_are_told_apart() -> None:
    assert is_code("```\nx\n```")
    assert is_code("~~~\nx\n~~~")
    assert not is_code("Use `x` here.")


def test_a_plain_paste_is_unchanged() -> None:
    text = (
        "One line\nand the next.\n\n"
        "    Indented four spaces\n    is still prose.\n\n"
        "#hashtag is not a heading"
    )
    assert blocks_of(text) == [
        "One line and the next.",
        "Indented four spaces is still prose.",
        "#hashtag is not a heading",
    ]


def test_a_sentence_is_found_whatever_marks_either_side_kept() -> None:
    block = "Trees give **shade** and make the air [cleaner](https://example.com)."
    assert contains(block, "Trees give shade and make the air cleaner.")
    assert contains(block, "give **shade**")
    assert not contains(block, "Trees give cleaner air.")
    # Whole words only.
    assert not contains(block, "ree")
