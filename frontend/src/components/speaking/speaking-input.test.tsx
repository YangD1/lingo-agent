import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { SpeakingInput, TAP_MS } from "./speaking-input";

vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const speech = vi.hoisted(() => ({ stopSpeaking: vi.fn(), unlockSpeech: vi.fn() }));
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  ...speech,
}));
// A recorder that records nothing: what it was told, and its state.
const rec = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), cancel: vi.fn(), maxSeconds: 0 }));
vi.mock("@/components/chat/use-recorder", async () => {
  const { useState } = await import("react");
  return {
    useRecorder: (_: unknown, options: { maxSeconds: number }) => {
      const [recording, setRecording] = useState(false);
      rec.maxSeconds = options.maxSeconds;
      return {
        recording,
        seconds: 0,
        level: 0,
        error: null,
        start: async () => {
          rec.start();
          setRecording(true);
        },
        stop: () => {
          rec.stop();
          setRecording(false);
        },
        cancel: () => {
          rec.cancel();
          setRecording(false);
        },
      };
    },
  };
});

// jsdom has no PointerEvent: without one, the pointer's position is lost.
if (!("PointerEvent" in window)) {
  Object.defineProperty(window, "PointerEvent", { value: class extends MouseEvent {} });
}

let now = 0;
const onTypingChange = vi.fn();

function show(props: Partial<Parameters<typeof SpeakingInput>[0]> = {}) {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeakingInput
        streaming={false}
        disabled={false}
        voice
        typing={false}
        onTypingChange={onTypingChange}
        onSend={async () => true}
        onVoice={() => {}}
        onStop={() => {}}
        {...props}
      />
    </NextIntlClientProvider>,
  );
  const mic = screen.getByTestId("speaking-mic");
  mic.getBoundingClientRect = () => ({ left: 0, right: 64, top: 0, bottom: 64 }) as DOMRect;
  return mic;
}

async function press(mic: HTMLElement, { heldMs, at = 10 }: { heldMs: number; at?: number }) {
  await act(async () => {
    fireEvent.pointerDown(mic, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
  });
  now += heldMs;
  await act(async () => {
    fireEvent.pointerUp(mic, { button: 0, pointerId: 1, clientX: at, clientY: 10 });
  });
}

beforeEach(() => {
  now = 1_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  Object.values(rec).forEach((v) => typeof v === "function" && v.mockReset());
  Object.values(speech).forEach((v) => v.mockReset());
  onTypingChange.mockReset();
});

afterEach(() => vi.restoreAllMocks());

describe("SpeakingInput", () => {
  it("holds to talk and sends on release, stopping the tutor first", async () => {
    const mic = show();
    expect(rec.maxSeconds).toBe(60);
    await act(async () => {
      fireEvent.pointerDown(mic, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    });
    expect(speech.stopSpeaking).toHaveBeenCalled();
    expect(rec.start).toHaveBeenCalled();
    expect(screen.getByText("Release to send · slide away to cancel")).toBeInTheDocument();
    now += TAP_MS + 200;
    await act(async () => {
      fireEvent.pointerUp(mic, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    });
    expect(rec.stop).toHaveBeenCalled();
    expect(speech.unlockSpeech).toHaveBeenCalled();
  });

  it("drops the recording when released outside the button", async () => {
    const mic = show();
    await act(async () => {
      fireEvent.pointerDown(mic, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    });
    fireEvent.pointerMove(mic, { pointerId: 1, clientX: 200, clientY: 10 });
    expect(screen.getByText("Release to cancel")).toBeInTheDocument();
    now += 1000;
    await act(async () => {
      fireEvent.pointerUp(mic, { button: 0, pointerId: 1, clientX: 200, clientY: 10 });
    });
    expect(rec.cancel).toHaveBeenCalled();
    expect(rec.stop).not.toHaveBeenCalled();
  });

  it("a tap starts, and the next tap sends", async () => {
    const mic = show();
    await press(mic, { heldMs: 100 });
    expect(rec.start).toHaveBeenCalledTimes(1);
    expect(rec.stop).not.toHaveBeenCalled();
    expect(screen.getByText("Tap again to send")).toBeInTheDocument();
    await press(mic, { heldMs: 50 });
    expect(rec.start).toHaveBeenCalledTimes(1);
    expect(rec.stop).toHaveBeenCalled();
  });

  it("space held down talks, unless typing", async () => {
    show();
    fireEvent.keyDown(window, { code: "Space" });
    expect(rec.start).toHaveBeenCalled();
    await act(async () => {});
    fireEvent.keyUp(window, { code: "Space" });
    expect(rec.stop).toHaveBeenCalled();
  });

  it("switches to typing, and only types without speech-to-text", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Type instead" }));
    expect(onTypingChange).toHaveBeenCalledWith(true);

    render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <SpeakingInput
          streaming={false}
          disabled={false}
          voice={false}
          typing={false}
          onTypingChange={onTypingChange}
          onSend={async () => true}
          onVoice={() => {}}
          onStop={() => {}}
        />
      </NextIntlClientProvider>,
    );
    expect(screen.getAllByTestId("speaking-mic")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Type in English…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Talk instead" })).not.toBeInTheDocument();
  });
});
