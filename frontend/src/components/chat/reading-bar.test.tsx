import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { type WorkspaceOpener, WorkspaceOpenerContext } from "@/components/workspace/opener";

import en from "../../../messages/en.json";
import { ReadingBar } from "./reading-bar";

function show(workspace: WorkspaceOpener | null = null) {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <WorkspaceOpenerContext value={workspace}>
        <ReadingBar articleId={7} />
      </WorkspaceOpenerContext>
    </NextIntlClientProvider>,
  );
}

describe("ReadingBar", () => {
  it("leads back to the article the conversation is about", () => {
    show();
    expect(screen.getByTestId("reading-bar")).toHaveTextContent("About an article you are reading");
    expect(screen.getByRole("link", { name: "Back to the article" })).toHaveAttribute("href", "/reading/7");
    expect(screen.queryByRole("button", { name: "Read in the workspace" })).not.toBeInTheDocument();
  });

  it("opens the article in the workspace on the chat page", async () => {
    let done = () => {};
    const workspace = {
      open: vi.fn(),
      openFrom: vi.fn(() => new Promise<void>((resolve) => (done = resolve))),
    };
    show(workspace);
    const button = screen.getByRole("button", { name: "Read in the workspace" });
    await userEvent.click(button);
    expect(workspace.openFrom).toHaveBeenCalledWith({ source: "article", id: 7 });
    expect(button).toBeDisabled();
    done();
    await vi.waitFor(() => expect(button).toBeEnabled());
  });
});
