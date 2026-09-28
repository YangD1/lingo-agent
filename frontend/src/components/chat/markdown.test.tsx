import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

function html(md: string) {
  return render(<Markdown>{md}</Markdown>).container;
}

describe("Markdown", () => {
  it("renders bold next to curly quotes", () => {
    const c = html("你好！In English, you can say **“Hello!”** How are you today?");
    expect(c.querySelector("strong")?.textContent).toBe("“Hello!”");
    expect(c.textContent).not.toContain("**");
  });

  it("renders bold when ** touches CJK text and punctuation", () => {
    const c = html("这是**“重点”**的意思，**该星号不会被识别。**这句话");
    expect([...c.querySelectorAll("strong")].map((s) => s.textContent)).toEqual([
      "“重点”",
      "该星号不会被识别。",
    ]);
  });

  it("renders lists, code and GFM tables", () => {
    const c = html("- one\n- two\n\n`inline`\n\n```\nblock\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(c.querySelectorAll("li")).toHaveLength(2);
    expect(c.querySelector("pre code")?.textContent).toBe("block\n");
    expect(c.querySelector("td")?.textContent).toBe("1");
  });

  it("does not render raw HTML", () => {
    const c = html('<img src=x onerror="alert(1)"> <b>hi</b>');
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("b")).toBeNull();
  });

  it("opens links in a new tab without leaking the opener", () => {
    const a = html("[docs](https://example.com)").querySelector("a");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
    expect(a).not.toHaveAttribute("node");
  });
});
