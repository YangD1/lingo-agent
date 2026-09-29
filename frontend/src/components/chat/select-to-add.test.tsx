import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import en from "../../../messages/en.json";
import { pickedWord, SelectToAdd } from "./select-to-add";

const addMine = vi.hoisted(() => vi.fn());
vi.mock("@/lib/vocab", () => ({ addMine }));

function Chat() {
  const ref = useRef<HTMLOListElement>(null);
  return (
    <>
      <ol ref={ref}>
        <li data-role="user">
          <div data-slot="message">I went home</div>
        </li>
        <li data-role="assistant">
          <div data-slot="message">
            <p>You went home reluctantly.</p>
          </div>
        </li>
      </ol>
      <SelectToAdd container={ref} />
    </>
  );
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <Chat />
    </NextIntlClientProvider>,
  );
}

/** Select `text` inside the element whose text is `within`, and tell listeners. */
function select(within: string, text: string) {
  const node = screen.getByText(within).firstChild as Text;
  const start = node.data.indexOf(text);
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, start + text.length);
  const selection = document.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  act(() => {
    document.dispatchEvent(new Event("selectionchange"));
  });
}

beforeEach(() => {
  addMine.mockReset();
  Range.prototype.getBoundingClientRect = () => new DOMRect(10, 20, 30, 16);
});
afterEach(() => document.getSelection()?.removeAllRanges());

describe("pickedWord", () => {
  it("takes one word from a tutor reply, and nothing else", () => {
    const { container } = show();
    select("You went home reluctantly.", "went");
    expect(pickedWord(document.getSelection(), container)).toEqual({
      word: "went",
      top: 40,
      left: 10,
    });
    select("You went home reluctantly.", "went home");
    expect(pickedWord(document.getSelection(), container)).toBeNull();
    select("I went home", "went");
    expect(pickedWord(document.getSelection(), container)).toBeNull();
  });
});

describe("SelectToAdd", () => {
  it("adds the selected word and says what was added", async () => {
    addMine.mockResolvedValueOnce({
      card: { word: { word: "go" } },
      matched: "lemma",
      added: true,
    });
    show();
    expect(screen.queryByRole("button")).toBeNull();

    select("You went home reluctantly.", "went");
    fireEvent.click(screen.getByRole("button", { name: "Add went to my words" }));

    expect(addMine).toHaveBeenCalledWith("went");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Added “go” (the base form of “went”).",
    );
    expect(document.getSelection()?.isCollapsed).toBe(true);
  });

  it("shows why a word could not be added", async () => {
    addMine.mockRejectedValueOnce(new ApiError(404, "word_not_found", "no such word"));
    show();
    select("You went home reluctantly.", "reluctantly");
    fireEvent.click(screen.getByRole("button", { name: "Add reluctantly to my words" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/dictionary/i);
  });

  it("offers nothing for the learner's own messages", () => {
    show();
    select("I went home", "went");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
