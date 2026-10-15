import { describe, expect, it } from "vitest";

import { pastedText, sourceToMarkdown } from "./paste";

describe("pastedText from the clipboard's HTML", () => {
  it("keeps a web article's headings, lists, tables, emphasis and links", () => {
    const html = `<meta charset="utf-8"><!--StartFragment-->
      <nav><a href="/">Home</a> · <a href="/news">News</a></nav>
      <article>
        <h1>Why Cities Plant Trees</h1>
        <p>Trees <strong>cool</strong> streets and <em>clean</em> the air. See <a href="https://example.org/trees">the study</a>.</p>
        <img src="tree.jpg" alt="A tree">
        <h2>Benefits</h2>
        <ul><li>Shade</li><li>Less noise</li></ul>
        <ol><li>Plan</li><li>Plant</li></ol>
        <table><thead><tr><th>City</th><th>Trees</th></tr></thead>
          <tbody><tr><td>Paris</td><td>200,000</td></tr></tbody></table>
        <blockquote><p>Plant today.</p></blockquote>
        <script>alert(1)</script><style>p { color: red }</style>
      </article><!--EndFragment-->`;
    const plain = "Why Cities Plant Trees\nTrees cool streets...";

    expect(pastedText(html, plain)).toBe(
      [
        "# Why Cities Plant Trees",
        "Trees **cool** streets and *clean* the air. See [the study](https://example.org/trees).",
        "## Benefits",
        "- Shade\n- Less noise",
        "1. Plan\n2. Plant",
        "| City | Trees |\n| --- | --- |\n| Paris | 200,000 |",
        "> Plant today.",
      ].join("\n\n"),
    );
  });

  it("reads Google Docs' styled spans and drops its bold wrapper", () => {
    const html =
      '<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1234">' +
      '<h2 dir="ltr"><span style="font-weight:700;">Results</span></h2>' +
      '<p dir="ltr"><span style="font-weight:400;">Sales were </span><span style="font-weight:700;">up</span>' +
      '<span style="font-weight:400;"> and </span><span style="font-style:italic;">steady</span>.</p>' +
      '<div><table><tbody><tr><td><p><span>Year</span></p></td><td><p><span>Sales</span></p></td></tr>' +
      "<tr><td><p><span>2025</span></p></td><td><p><span>12</span></p></td></tr></tbody></table></div></b>";

    expect(pastedText(html, "Results\nSales were up and steady.")).toBe(
      "## Results\n\nSales were **up** and *steady*.\n\n| Year | Sales |\n| --- | --- |\n| 2025 | 12  |",
      // The table plugin pads a cell to three characters.
    );
  });

  it("turns Word's list paragraphs into lists", () => {
    const html =
      "<html xmlns:o=\"urn:schemas-microsoft-com:office:office\"><head><style>p.MsoNormal{}</style></head><body>" +
      "<!--[if gte mso 9]><xml></xml><![endif]-->" +
      "<p class=MsoNormal><b>Agenda</b><o:p></o:p></p>" +
      "<p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>·<span>&nbsp;&nbsp;</span></span>Welcome<o:p></o:p></p>" +
      "<p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>·<span>&nbsp;&nbsp;</span></span>Budget<o:p></o:p></p>" +
      "<p class=MsoListParagraph style='mso-list:l1 level1 lfo2'><span style='mso-list:Ignore'>1.<span>&nbsp;</span></span>Vote<o:p></o:p></p>" +
      "</body></html>";

    expect(pastedText(html, "Agenda\n·  Welcome\n·  Budget\n1. Vote")).toBe(
      "**Agenda**\n\n- Welcome\n- Budget\n\n1. Vote",
    );
  });

  it("escapes Markdown characters that were plain text on the page", () => {
    expect(pastedText("<p>Use <b>1</b> *star* here</p>", "Use 1 *star* here")).toBe("Use **1** \\*star\\* here");
  });

  it("keeps code blocks and table cells as Markdown, never as HTML", () => {
    const html =
      '<h3>Example</h3><pre><code class="language-html">&lt;b&gt;hi&lt;/b&gt;</code></pre>' +
      "<table><tr><th>Tag</th><th>Use</th></tr><tr><td><code>&lt;b&gt;</code></td><td><p>bold</p><p>text</p></td></tr></table>";

    expect(pastedText(html, "")).toBe(
      "### Example\n\n```html\n<b>hi</b>\n```\n\n| Tag | Use |\n| --- | --- |\n| `<b>` | bold text |",
    );
  });

  it("keeps a link's text only when its address isn't a web or mail link", () => {
    const html = '<p><a href="javascript:alert(1)">click</a> <a href="/local">here</a> <a href="mailto:a@b.co">mail</a></p>';
    expect(pastedText(html, "")).toBe("click here [mail](mailto:a@b.co)");
  });

  it("uses the plain text when the HTML adds no structure", () => {
    expect(pastedText("<p>Just a sentence.</p>", "Just a sentence.")).toBe("Just a sentence.");
  });

  it("uses the plain text for code copied from an editor", () => {
    const html =
      '<div style="font-family: Consolas; white-space: pre;"><div><span style="font-weight: bold;">def</span> f():</div>' +
      "<div>    return 1</div></div>";
    const plain = "def f():\n    return 1";
    expect(pastedText(html, plain)).toBe(plain);
  });
});

describe("sourceToMarkdown", () => {
  it("leaves plain text and Markdown alone", () => {
    const text = "# Title\n\n- a\n- b\n\nIf a < b and c > d, use Array<string>.";
    expect(sourceToMarkdown(text)).toBe(text);
  });

  it("converts HTML source pasted as text", () => {
    const text = `<!doctype html>
<html><head><title>T</title><script>steal()</script></head>
<body>
  <h2>News</h2>
  <p>A <b>big</b> day.</p>

  <ul>
    <li>One</li>
    <li>Two</li>
  </ul>
  <iframe src="https://evil.example"></iframe>
</body></html>`;
    expect(sourceToMarkdown(text)).toBe("## News\n\nA **big** day.\n\n- One\n- Two");
  });

  it("converts tags mixed into Markdown and keeps the Markdown as typed", () => {
    const text = [
      "## Notes",
      "",
      "- item with <b>bold</b> and *stars*",
      "  - nested <em>one</em>",
      "",
      "<p>An HTML <i>paragraph</i></p>",
      "",
      "Line one<br>still going",
      "",
      "<script>",
      "evil()",
      "",
      "more()",
      "</script>",
      "",
      "Done.",
    ].join("\n");
    expect(sourceToMarkdown(text)).toBe(
      [
        "## Notes",
        "",
        "- item with **bold** and *stars*",
        "  - nested *one*",
        "",
        "An HTML *paragraph*",
        "",
        "Line one  \nstill going",
        "",
        "",
        "",
        "Done.",
      ].join("\n"),
    );
  });

  it("leaves HTML inside fenced and inline code alone", () => {
    const text = [
      "Use `<b>` for <b>bold</b>:",
      "",
      "```html",
      "<p>Hello <b>world</b></p>",
      "",
      "<script>run()</script>",
      "```",
      "",
      "After <em>code</em>.",
    ].join("\n");
    expect(sourceToMarkdown(text)).toBe(
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
      ].join("\n"),
    );
  });
});
