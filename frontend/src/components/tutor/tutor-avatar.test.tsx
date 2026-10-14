import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { levelWatched, setLevelSource } from "@/lib/voice-level";

import { TutorAvatar } from "./tutor-avatar";

// jsdom has no 2D canvas: a context that records the calls drawing makes.
const calls: string[] = [];
const fakeContext = () =>
  new Proxy({} as Record<string | symbol, unknown>, {
    get: (target, key) =>
      key in target
        ? target[key]
        : (target[key] = () => {
            calls.push(String(key));
          }),
    set: (target, key, value) => {
      target[key] = value;
      return true;
    },
  });

class FakePath2D {
  moveTo() {}
  lineTo() {}
  bezierCurveTo() {}
  closePath() {}
}

let frames: FrameRequestCallback[] = [];
let reduced = false;
let hidden = false;

function tick(now: number) {
  const pending = frames;
  frames = [];
  act(() => pending.forEach((callback) => callback(now)));
}

function setHidden(value: boolean) {
  hidden = value;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  calls.length = 0;
  frames = [];
  reduced = false;
  hidden = false;
  vi.stubGlobal("Path2D", FakePath2D);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => fakeContext() as unknown as CanvasRenderingContext2D,
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
  vi.stubGlobal("cancelAnimationFrame", () => {
    frames = [];
  });
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("reduced-motion") && reduced,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.devicePixelRatio = 1;
});

describe("TutorAvatar", () => {
  it("is an image named by its label, drawn at the screen's pixel density", () => {
    window.devicePixelRatio = 2;
    render(<TutorAvatar outfit="classic" size={48} label="Lily" />);
    const canvas = screen.getByRole("img", { name: "Lily" }) as HTMLCanvasElement;
    tick(0);
    expect(canvas.width).toBe(96);
    expect(canvas.style.width).toBe("48px");
    expect(canvas.dataset.outfit).toBe("classic");
  });

  it("draws the plain cat for an outfit it doesn't know", () => {
    render(<TutorAvatar outfit="pirate" label="" />);
    const canvas = document.querySelector("canvas")!;
    expect(canvas.dataset.outfit).toBe("cat");
    expect(canvas.getAttribute("aria-hidden")).toBe("true");
  });

  it("keeps drawing a frame per refresh while animated", () => {
    render(<TutorAvatar label="JOJO" />);
    expect(frames).toHaveLength(1);
    tick(0);
    tick(16);
    expect(frames).toHaveLength(1);
    expect(calls).toContain("ellipse");
  });

  it("draws once and stays still with animation off", () => {
    render(<TutorAvatar animate={false} label="JOJO" />);
    expect(frames).toHaveLength(0);
    expect(calls).toContain("ellipse");
  });

  it("draws once and stays still when the system asks for less motion", () => {
    reduced = true;
    render(<TutorAvatar label="JOJO" />);
    expect(frames).toHaveLength(0);
    expect(document.querySelector("canvas")!.dataset.animated).toBeUndefined();
  });

  it("marks a still tutor that is talking with the speaker sign", () => {
    const { rerender } = render(<TutorAvatar animate={false} label="JOJO" />);
    const arcs = calls.filter((c) => c === "arc").length;
    calls.length = 0;
    rerender(<TutorAvatar animate={false} state="speaking" label="JOJO" />);
    expect(calls.filter((c) => c === "arc").length).toBeGreaterThan(arcs);
  });

  it("stops drawing while the page is hidden and picks up when it is back", () => {
    render(<TutorAvatar label="JOJO" />);
    setHidden(true);
    expect(frames).toHaveLength(0);
    setHidden(false);
    expect(frames).toHaveLength(1);
  });

  it("follows the voice level while speaking, and asks for it only while animated", () => {
    const level = vi.fn(() => 0.8);
    const stop = setLevelSource(level);
    const { rerender, unmount } = render(<TutorAvatar state="idle" label="JOJO" />);
    expect(levelWatched()).toBe(true);
    tick(0);
    expect(level).not.toHaveBeenCalled();
    rerender(<TutorAvatar state="speaking" label="JOJO" />);
    tick(16);
    expect(level).toHaveBeenCalled();
    unmount();
    expect(levelWatched()).toBe(false);
    stop();
  });
});
