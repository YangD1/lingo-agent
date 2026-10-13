import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_PET_PLACE, parsePetPlace } from "@/lib/preferences";
import { DEFAULT_TUTOR, type Tutor } from "@/lib/tutor";

import en from "../../../messages/en.json";
import { DOZE_SETTLE_MS, placeAfterDrop, TutorPet } from "./tutor-pet";

const tutor = vi.hoisted(() => ({ current: null as Tutor | null }));
vi.mock("@/lib/tutor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tutor")>()),
  useTutor: () => tutor.current,
}));

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

// The window has its own tests.
vi.mock("./pet-chat", () => ({
  PetChat: ({ side, onClose }: { side: string; onClose: () => void }) => (
    <div role="dialog" data-side={side}>
      <button onClick={onClose}>close window</button>
    </div>
  ),
}));

// jsdom has no 2D canvas; the avatar has its own tests.
vi.mock("./tutor-avatar", () => ({
  TutorAvatar: ({
    label,
    size,
    animate,
    state,
  }: {
    label: string;
    size: number;
    animate: boolean;
    state?: string;
  }) => (
    <span
      role={label ? "img" : undefined}
      aria-label={label || undefined}
      data-size={size}
      data-animate={String(animate)}
      data-state={state}
    />
  ),
}));

const PLACE_KEY = "lingo.tutorPet.place";
const stored = () => parsePetPlace(window.localStorage.getItem(PLACE_KEY));

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <TutorPet />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  nav.pathname = "/dashboard";
  tutor.current = { ...DEFAULT_TUTOR, name: "Max", display_name: "Max" };
  vi.stubGlobal("innerWidth", 1000);
  vi.stubGlobal("innerHeight", 800);
  // preferences also keeps what was set in memory: start each test from the default.
  window.localStorage.setItem(PLACE_KEY, JSON.stringify(DEFAULT_PET_PLACE));
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("TutorPet", () => {
  it("is not there when the learner turned it off, or before the tutor is known", () => {
    tutor.current = null;
    const { container, rerender } = show();
    expect(container).toBeEmptyDOMElement();
    tutor.current = { ...DEFAULT_TUTOR, pet: false };
    rerender(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <TutorPet />
      </NextIntlClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("sits on the right by default, drawn with the learner's animation switch", () => {
    tutor.current = { ...tutor.current!, animate: false };
    show();
    const pet = screen.getByTestId("tutor-pet");
    expect(pet).toHaveAttribute("data-side", "right");
    expect(pet.style.right).toBe("12px");
    expect(pet.style.bottom).toContain(`${DEFAULT_PET_PLACE.bottom}px`);
    expect(screen.getByRole("img", { name: "Max, your tutor" })).toHaveAttribute("data-animate", "false");
  });

  it("collapses to a small button and comes back, remembered on this device", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Collapse the desk pet" }));
    expect(stored().collapsed).toBe(true);
    expect(screen.getByTestId("tutor-pet").style.right).toBe("0px");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show Max, your desk pet" }));
    expect(stored().collapsed).toBe(false);
    expect(screen.getByRole("img", { name: "Max, your tutor" })).toBeInTheDocument();
  });

  it("is dragged to the nearer edge, at the height it was dropped", () => {
    show();
    const pet = screen.getByTestId("tutor-pet");
    pet.getBoundingClientRect = () => new DOMRect(900, 600, 88, 88);
    fireEvent.pointerDown(pet, { button: 0, pointerId: 1, clientX: 940, clientY: 640 });
    fireEvent.pointerMove(pet, { pointerId: 1, clientX: 700, clientY: 640 });
    // Still on the right half while moving: it follows the pointer.
    expect(pet.style.left).toBe("660px");
    fireEvent.pointerMove(pet, { pointerId: 1, clientX: 200, clientY: 340 });
    fireEvent.pointerUp(pet, { pointerId: 1, clientX: 200, clientY: 340 });

    expect(stored()).toEqual({ side: "left", bottom: 412, collapsed: false });
    expect(pet).toHaveAttribute("data-side", "left");
    expect(pet.style.left).toBe("12px");
  });

  it("takes a small wobble as a tap, not a drag", () => {
    show();
    const pet = screen.getByTestId("tutor-pet");
    pet.getBoundingClientRect = () => new DOMRect(900, 600, 88, 88);
    fireEvent.pointerDown(pet, { button: 0, pointerId: 1, clientX: 940, clientY: 640 });
    fireEvent.pointerMove(pet, { pointerId: 1, clientX: 942, clientY: 641 });
    fireEvent.pointerUp(pet, { pointerId: 1, clientX: 942, clientY: 641 });
    expect(stored()).toEqual(DEFAULT_PET_PLACE);
    // The collapse button still works after it.
    act(() => screen.getByRole("button", { name: "Collapse the desk pet" }).click());
    expect(stored().collapsed).toBe(true);
  });

  it("is smaller on a phone", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    show();
    expect(screen.getByRole("img")).toHaveAttribute("data-size", "64");
  });
});

describe("placeAfterDrop", () => {
  it("picks the edge by the box's center and keeps the height", () => {
    const viewport = { width: 1000, height: 800 };
    expect(placeAfterDrop({ left: 470, top: 0, width: 88, height: 88 }, viewport, true)).toEqual({
      side: "right",
      bottom: 712,
      collapsed: true,
    });
    expect(placeAfterDrop({ left: 400, top: 720, width: 88, height: 88 }, viewport, false)).toEqual({
      side: "left",
      bottom: 0,
      collapsed: false,
    });
  });
});

describe("parsePetPlace", () => {
  it("falls back to the default for anything malformed", () => {
    expect(parsePetPlace(null)).toEqual(DEFAULT_PET_PLACE);
    expect(parsePetPlace("{oops")).toEqual(DEFAULT_PET_PLACE);
    expect(parsePetPlace('{"side":"up","bottom":-5,"collapsed":"yes"}')).toEqual({
      ...DEFAULT_PET_PLACE,
      collapsed: false,
    });
    expect(parsePetPlace('{"side":"left","bottom":42.4,"collapsed":true}')).toEqual({
      side: "left",
      bottom: 42,
      collapsed: true,
    });
  });
});

describe("TutorPet reacting", () => {
  it("shows what the pages report, and stops drawing once it has dozed off", async () => {
    vi.useFakeTimers();
    try {
      const bus = await import("@/lib/tutor-pet");
      bus.resetPet();
      show();
      const avatar = () => screen.getByRole("img", { name: "Max, your tutor" });
      let stop = () => {};
      act(() => {
        stop = bus.petHold("listening");
      });
      expect(avatar()).toHaveAttribute("data-state", "listening");
      act(() => stop());

      act(() => bus.checkSleep(Date.now() + bus.SLEEP_AFTER_MS));
      expect(avatar()).toHaveAttribute("data-state", "sleeping");
      expect(avatar()).toHaveAttribute("data-animate", "true"); // still settling
      act(() => vi.advanceTimersByTime(DOZE_SETTLE_MS));
      expect(avatar()).toHaveAttribute("data-animate", "false");

      act(() => bus.petActivity());
      expect(avatar()).toHaveAttribute("data-state", "idle");
      expect(avatar()).toHaveAttribute("data-animate", "true");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("TutorPet chat", () => {
  it("opens the chat window on a tap, on its side, and closes it again", async () => {
    show();
    const pet = screen.getByRole("button", { name: "Chat with Max" });
    expect(pet).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(pet);
    expect(screen.getByRole("dialog")).toHaveAttribute("data-side", "right");
    expect(pet).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("button", { name: "close window" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("doesn't open after a drag", () => {
    show();
    const pet = screen.getByTestId("tutor-pet");
    pet.getBoundingClientRect = () => new DOMRect(900, 600, 88, 88);
    const button = screen.getByTestId("tutor-pet-button");
    fireEvent.pointerDown(button, { button: 0, pointerId: 1, clientX: 940, clientY: 640 });
    fireEvent.pointerMove(button, { pointerId: 1, clientX: 600, clientY: 640 });
    fireEvent.pointerUp(button, { pointerId: 1, clientX: 600, clientY: 640 });
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("on the chat page only puts the cursor in the message box", async () => {
    nav.pathname = "/chat";
    const input = document.createElement("textarea");
    input.setAttribute("data-chat-input", "");
    document.body.append(input);
    try {
      show();
      await userEvent.click(screen.getByRole("button", { name: "Max: type in the message box" }));
      expect(input).toHaveFocus();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    } finally {
      input.remove();
    }
  });
});
