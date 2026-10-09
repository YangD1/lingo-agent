import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";

// The settings with a read-aloud service (ADR 0028 §3, Q54a). The speech module keeps what
// the server reads for the page, so each test loads it afresh.

const ZIRA = {
  name: "Microsoft Zira - English (United States)",
  lang: "en-US",
  localService: true,
  default: false,
  voiceURI: "zira",
};

let tts: () => Response;

async function wrap(languages: string[]) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        url === "/api/speech/capabilities"
          ? Response.json({ tts: languages.length > 0, tts_languages: languages })
          : url === "/api/speech/tts-cache"
            ? Response.json({ deleted: 3 })
            : tts(),
      ),
    ),
  );
  const speech = await import("@/lib/speech");
  const { SpeechSettings } = await import("./speech-settings");
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeechSettings />
    </NextIntlClientProvider>,
  );
  await act(() => speech.loadCapabilities());
  return speech;
}

beforeEach(() => {
  tts = () => new Response(new Blob([new Uint8Array([1])]));
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => [ZIRA],
    speak: () => {},
    cancel: () => {},
  });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      constructor(public text: string) {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("SpeechSettings with a read-aloud service", () => {
  it("has no switch where the server doesn't read aloud", async () => {
    await wrap([]);
    expect(screen.queryByTestId("speech-server")).not.toBeInTheDocument();
    expect(screen.queryByText(/read-aloud service isn't available/)).not.toBeInTheDocument();
  });

  it("is on by default, marks the AI, and turns off for this browser", async () => {
    await wrap(["en-US", "en-GB"]);
    const toggle = screen.getByTestId("speech-server");
    expect(toggle).toBeChecked();
    expect(screen.getByTestId("ai-badge-read_aloud")).toBeInTheDocument();
    // The device's English voice is only the fallback now; Chinese is still the device's.
    expect(screen.getByText(/used when the read-aloud service isn't available/)).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(JSON.parse(window.localStorage.getItem("lingo.speech")!)).toMatchObject({
      server: false,
    });
    expect(screen.queryByText(/used when the read-aloud service isn't available/)).toBeNull();
  });

  it("says when the server failed on this page", async () => {
    const speech = await wrap(["en-US"]);
    tts = () => Response.json({ detail: { code: "tts_unavailable", message: "x" } }, { status: 502 });
    act(() => speech.speak("Hello."));
    await waitFor(() =>
      expect(screen.getByText(/isn't working on this page/)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("speech-server")).toHaveAttribute("aria-disabled", "true");
  });

  it("marks read-aloud buttons as AI only while the server reads English", async () => {
    window.localStorage.setItem("lingo.speech", JSON.stringify({ accent: "en-GB" }));
    await wrap(["en-US"]); // no British voice on the server
    const { ReadAloudBadge } = await import("./read-aloud-badge");
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <ReadAloudBadge />
      </NextIntlClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();

    act(() => window.localStorage.setItem("lingo.speech", JSON.stringify({ accent: "en-US" })));
    act(() => window.dispatchEvent(new Event("lingo:speech")));
    expect(container.querySelector('[data-testid="ai-badge-read_aloud"]')).not.toBeNull();

    act(() => window.localStorage.setItem("lingo.speech", JSON.stringify({ server: false })));
    act(() => window.dispatchEvent(new Event("lingo:speech")));
    expect(container).toBeEmptyDOMElement();
  });

  it("clears the learner's own read-aloud audio after asking", async () => {
    await wrap(["en-US"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear my read-aloud cache" }));
    expect(fetch).not.toHaveBeenCalledWith("/api/speech/tts-cache", expect.anything());
    expect(screen.getByText(/billed\) again next time/)).toBeInTheDocument();

    const confirm = screen.getAllByRole("button", { name: "Clear my read-aloud cache" }).at(-1)!;
    await userEvent.click(confirm);

    expect(fetch).toHaveBeenCalledWith("/api/speech/tts-cache", expect.objectContaining({ method: "DELETE" }));
    expect(await screen.findByText("Deleted 3 recordings.")).toBeInTheDocument();
  });
});
