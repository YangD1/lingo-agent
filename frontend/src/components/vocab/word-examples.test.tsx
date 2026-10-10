import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { WordExamples } from "./word-examples";

const shadowing = vi.hoisted(() => ({ mode: null as "assessment" | "rough" | null }));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => shadowing.mode,
}));

const SENTENCES = [
  { en: "She left early.", zh: "她早早离开了。", source: "tatoeba", url: null },
  { en: "We left the door open.", zh: "我们没关门。", source: "tatoeba", url: null },
];

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <WordExamples wordId={42} sentences={SENTENCES} forms={["left"]} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  shadowing.mode = null;
});

describe("shadowing an example sentence", () => {
  it("offers nothing while shadowing can't be scored", () => {
    show();
    expect(screen.queryByTestId("shadowing-open")).not.toBeInTheDocument();
    expect(screen.queryByTestId("examples-shadowing-hint")).not.toBeInTheDocument();
  });

  it("opens the panel for that sentence alone", async () => {
    shadowing.mode = "assessment";
    show();
    expect(screen.getByTestId("examples-shadowing-hint")).toBeInTheDocument();
    const mics = screen.getAllByRole("button", { name: "Shadow this sentence" });
    expect(mics).toHaveLength(2);

    await userEvent.click(mics[1]);
    expect(screen.queryByTestId("shadowing-sentences")).not.toBeInTheDocument();
    expect(screen.getByTestId("shadowing-sentence")).toHaveTextContent("We left the door open.");
    await userEvent.click(mics[1]);
    expect(screen.queryByTestId("shadowing-panel")).not.toBeInTheDocument();
  });
});
