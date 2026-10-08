import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "../../../messages/en.json";
import { ReadingBar } from "./reading-bar";

describe("ReadingBar", () => {
  it("leads back to the article the conversation is about", () => {
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <ReadingBar articleId={7} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByTestId("reading-bar")).toHaveTextContent("About an article you are reading");
    expect(screen.getByRole("link", { name: "Back to the article" })).toHaveAttribute("href", "/reading/7");
  });
});
