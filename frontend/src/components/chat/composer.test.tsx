import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { PASTE_HINT_CHARS } from "@/lib/workspace";

import en from "../../../messages/en.json";
import { Composer, type ComposerHandle } from "./composer";
import { useAttachments } from "./use-attachments";

function Box({ disabled, autoFocus }: { disabled: boolean; autoFocus?: boolean }) {
  const tray = useAttachments(null, async () => "c1");
  return (
    <Composer
      streaming={false}
      disabled={disabled}
      tray={tray}
      onSend={vi.fn()}
      onStop={vi.fn()}
      autoFocus={autoFocus}
    />
  );
}

function show(props: { disabled: boolean; autoFocus?: boolean }) {
  const view = render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <Box {...props} />
    </NextIntlClientProvider>,
  );
  return (next: { disabled: boolean; autoFocus?: boolean }) =>
    view.rerender(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <Box {...next} />
      </NextIntlClientProvider>,
    );
}

describe("Composer", () => {
  it("with autoFocus, takes the cursor once the history has loaded", () => {
    const update = show({ disabled: true, autoFocus: true });
    const input = screen.getByRole("textbox");
    expect(input).not.toHaveFocus();
    update({ disabled: false, autoFocus: true });
    expect(input).toHaveFocus();
  });

  it("leaves the cursor alone without it", () => {
    show({ disabled: false });
    expect(screen.getByRole("textbox")).not.toHaveFocus();
  });
});

function Pasting({
  onOpen,
  handle,
}: {
  onOpen?: (kind: "reading" | "writing", text: string) => Promise<boolean>;
  handle?: React.Ref<ComposerHandle>;
}) {
  const tray = useAttachments(null, async () => "c1");
  return (
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <Composer
        streaming={false}
        tray={tray}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onOpenInWorkspace={onOpen}
        ref={handle}
      />
    </NextIntlClientProvider>
  );
}

/** Paste `text` the way a browser does: the event, then the text in the box. */
function paste(input: HTMLElement, text: string) {
  fireEvent.paste(input, { clipboardData: { files: [], getData: () => text } });
  fireEvent.change(input, { target: { value: (input as HTMLTextAreaElement).value + text } });
}

describe("Composer: long pastes and quotes (ADR 0043 §4)", () => {
  const long = "The quick brown fox. ".repeat(Math.ceil(PASTE_HINT_CHARS / 20));

  it("offers the workspace for a long pasted text, and not for a short one", () => {
    render(<Pasting onOpen={vi.fn()} />);
    const input = screen.getByRole("textbox");
    paste(input, "A short note.");
    expect(screen.queryByTestId("paste-hint")).not.toBeInTheDocument();
    paste(input, long);
    expect(screen.getByTestId("paste-hint")).toHaveTextContent("That's a long text");
  });

  it("offers nothing where there is no workspace", () => {
    render(<Pasting />);
    paste(screen.getByRole("textbox"), long);
    expect(screen.queryByTestId("paste-hint")).not.toBeInTheDocument();
  });

  it("opens the whole text in the workspace and takes it out of the box", async () => {
    const onOpen = vi.fn(() => Promise.resolve(true));
    render(<Pasting onOpen={onOpen} />);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "Please look:");
    paste(input, long);
    await userEvent.click(screen.getByRole("button", { name: "Read closely" }));
    expect(onOpen).toHaveBeenCalledWith("reading", long);
    await waitFor(() => expect(input).toHaveValue("Please look:"));
    expect(screen.queryByTestId("paste-hint")).not.toBeInTheDocument();
  });

  it("keeps the text and the offer when opening fails", async () => {
    const onOpen = vi.fn(() => Promise.resolve(false));
    render(<Pasting onOpen={onOpen} />);
    const input = screen.getByRole("textbox");
    paste(input, long);
    await userEvent.click(screen.getByRole("button", { name: "Review as writing" }));
    expect(onOpen).toHaveBeenCalledWith("writing", long);
    expect(input).toHaveValue(long);
    expect(screen.getByTestId("paste-hint")).toBeInTheDocument();
  });

  it("dismissing the offer leaves the text to send", async () => {
    render(<Pasting onOpen={vi.fn()} />);
    const input = screen.getByRole("textbox");
    paste(input, long);
    await userEvent.click(screen.getByRole("button", { name: "No, just send it" }));
    expect(screen.queryByTestId("paste-hint")).not.toBeInTheDocument();
    expect(input).toHaveValue(long);
  });

  it("adds a quote after what was typed and puts the cursor below it", async () => {
    const handle = createRef<ComposerHandle>();
    render(<Pasting handle={handle} />);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "Why?");
    act(() => handle.current?.addQuote("> The fox ran."));
    expect(input).toHaveValue("Why?\n\n> The fox ran.\n\n");
    expect(input).toHaveFocus();
  });
});
