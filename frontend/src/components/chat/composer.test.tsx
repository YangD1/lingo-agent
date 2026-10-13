import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { Composer } from "./composer";
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
