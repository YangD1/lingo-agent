import { afterEach, describe, expect, it, vi } from "vitest";

import { applyFont, FONT_BOOT_SCRIPT, FONT_KEY, parseFontChoice } from "./font-choice";

function fontLinks(): string[] {
  return [...document.querySelectorAll<HTMLLinkElement>("link[data-font-css]")].map((l) =>
    l.getAttribute("href")!,
  );
}

function boot(): void {
  // The script is a string for <head>; run it the way the browser would.
  new Function(FONT_BOOT_SCRIPT)();
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.head.innerHTML = "";
  delete document.documentElement.dataset.font;
});

describe("parseFontChoice", () => {
  it("keeps known choices and falls back to the default", () => {
    expect(parseFontChoice("wenkai")).toBe("wenkai");
    expect(parseFontChoice("system")).toBe("system");
    expect(parseFontChoice(null)).toBe("sans");
    expect(parseFontChoice("comic-sans")).toBe("sans");
  });
});

describe("applyFont", () => {
  it("sets the choice on <html> and links its stylesheet once", () => {
    applyFont("serif");
    applyFont("serif");

    expect(document.documentElement.dataset.font).toBe("serif");
    expect(fontLinks()).toEqual(["/fonts/serif/font.css"]);
  });

  it("links nothing for system fonts", () => {
    applyFont("system");

    expect(document.documentElement.dataset.font).toBe("system");
    expect(fontLinks()).toEqual([]);
  });
});

describe("FONT_BOOT_SCRIPT", () => {
  it("applies the stored choice before the page renders", () => {
    window.localStorage.setItem(FONT_KEY, "wenkai");
    boot();

    expect(document.documentElement.dataset.font).toBe("wenkai");
    expect(fontLinks()).toEqual(["/fonts/wenkai/font.css"]);
  });

  it("uses the default for nothing stored or an unknown value", () => {
    window.localStorage.setItem(FONT_KEY, "../../evil");
    boot();

    expect(document.documentElement.dataset.font).toBe("sans");
    expect(fontLinks()).toEqual(["/fonts/sans/font.css"]);
  });

  it("uses the default when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    boot();

    expect(document.documentElement.dataset.font).toBe("sans");
  });

  it("links nothing for system fonts", () => {
    window.localStorage.setItem(FONT_KEY, "system");
    boot();

    expect(document.documentElement.dataset.font).toBe("system");
    expect(fontLinks()).toEqual([]);
  });
});
