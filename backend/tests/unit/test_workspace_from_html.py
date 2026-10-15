"""HTML in a text for reading becomes Markdown (task 85, the backend's fallback)."""

from app.workspace.from_html import from_html
from app.workspace.service import reading_text


def test_text_without_html_is_unchanged() -> None:
    text = "# Title\n\n- a\n- b\n\nIf a < b and c > d, use Array<string>."
    assert from_html(text) == text


def test_an_html_page_becomes_markdown() -> None:
    page = """<!doctype html>
<html><head><title>T</title><script>steal()</script><style>p{}</style></head>
<body>
  <nav><a href="/">Home</a></nav>
  <h1>Street trees</h1>
  <p>
    Trees <strong>cool</strong> streets and <em>clean</em> the air.
    See <a href="https://example.org/a b">the study</a> or <a href="javascript:x()">this</a>.
  </p>
  <img src="tree.jpg" onerror="x()">
  <ul>
    <li>Shade</li>
    <li>Less noise
      <ol><li>at night</li><li>by day</li></ol>
    </li>
  </ul>
  <table>
    <tr><td><p>City</p></td><td>Trees</td></tr>
    <tr><td>Paris</td><td>200 | 300</td></tr>
  </table>
  <blockquote><p>Plant today.</p><p>Water tomorrow.</p></blockquote>
  <pre><code>&lt;b&gt;hi&lt;/b&gt;
  indented</code></pre>
  <p>Line one<br>line two</p>
  <iframe src="https://evil.example"><p>inside</p></iframe>
  <form><input value="x"><button>Go</button></form>
</body></html>"""
    assert from_html(page) == "\n".join(
        [
            "# Street trees",
            "",
            "Trees **cool** streets and *clean* the air. See [the study](https://example.org/a%20b)"
            " or this.",
            "",
            "- Shade",
            "- Less noise",
            "  1. at night",
            "  2. by day",
            "",
            "| City | Trees |",
            "| --- | --- |",
            "| Paris | 200 \\| 300 |",
            "",
            "> Plant today.",
            ">",
            "> Water tomorrow.",
            "",
            "```",
            "<b>hi</b>",
            "  indented",
            "```",
            "",
            "Line one",
            "line two",
        ]
    )


def test_tags_in_markdown_become_marks_and_the_markdown_stays() -> None:
    text = "\n".join(
        [
            "## Notes",
            "",
            "- item with <b>bold</b> and *stars*",
            "  - nested <em>one</em>",
            "",
            "<p>An HTML <i>paragraph</i></p>",
            "",
            "<script>",
            "evil()",
            "",
            "more()",
            "</script>",
            "",
            "Done.",
        ]
    )
    assert from_html(text) == "\n".join(
        [
            "## Notes",
            "",
            "- item with **bold** and *stars*",
            "  - nested *one*",
            "",
            "An HTML *paragraph*",
            "",
            "Done.",
        ]
    )


def test_html_inside_code_is_left_alone() -> None:
    text = "\n".join(
        [
            "Use `<b>` for <b>bold</b>:",
            "",
            "```html",
            "<p>Hello <b>world</b></p>",
            "",
            "<script>run()</script>",
            "```",
            "",
            "After <em>code</em>.",
        ]
    )
    assert from_html(text) == "\n".join(
        [
            "Use `<b>` for **bold**:",
            "",
            "```html",
            "<p>Hello <b>world</b></p>",
            "",
            "<script>run()</script>",
            "```",
            "",
            "After *code*.",
        ]
    )


def test_a_reading_document_from_html_keeps_its_blocks() -> None:
    text = reading_text(
        "<h2>News</h2><p>A <b>big</b> day for the city.</p><ul><li>One</li><li>Two</li></ul>"
        "<script>alert(1)</script>"
    )
    paragraphs = ["## News", "A **big** day for the city.", "- One\n- Two"]
    assert text.content == {"paragraphs": paragraphs}
    assert text.title == "News"
