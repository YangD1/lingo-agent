import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it } from "vitest";

import { FONT_KEY } from "@/lib/font-choice";

import en from "../../../messages/en.json";
import { DisplaySection } from "./display-section";

function renderSection() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <DisplaySection />
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  window.localStorage.clear();
  document.head.innerHTML = "";
  delete document.documentElement.dataset.font;
});

describe("DisplaySection font", () => {
  it("starts on the default and previews every font in its own stack", () => {
    renderSection();

    expect(screen.getByRole("radio", { name: /Default: Inter/ })).toBeChecked();
    expect(screen.getByTestId("font-sample-wenkai")).toHaveStyle({
      fontFamily: "var(--font-stack-wenkai)",
    });
    // Previews link every stylesheet (system fonts have none).
    expect(document.querySelectorAll("link[data-font-css]")).toHaveLength(3);
  });

  it("switches the page font at once and remembers it", async () => {
    renderSection();

    await userEvent.click(screen.getByRole("radio", { name: /LXGW WenKai/ }));

    expect(screen.getByRole("radio", { name: /LXGW WenKai/ })).toBeChecked();
    expect(document.documentElement.dataset.font).toBe("wenkai");
    expect(window.localStorage.getItem(FONT_KEY)).toBe("wenkai");
  });
});
