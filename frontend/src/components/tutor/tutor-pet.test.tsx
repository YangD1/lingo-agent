import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Advice } from "@/lib/advice";
import { SETTLE_MS } from "@/lib/pet-nudges";
import { DEFAULT_PET_PLACE, parsePetPlace } from "@/lib/preferences";
import { DEFAULT_TUTOR, type Tutor } from "@/lib/tutor";
import { checkSleep, petActivity, petPlanDone, resetPet, SLEEP_AFTER_MS } from "@/lib/tutor-pet";
import { announceReviewed } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { DOZE_SETTLE_MS, placeAfterDrop, TutorPet } from "./tutor-pet";

const tutor = vi.hoisted(() => ({ current: null as Tutor | null }));
vi.mock("@/lib/tutor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tutor")>()),
  useTutor: () => tutor.current,
}));

const nav = vi.hoisted(() => ({ pathname: "/dashboard", search: "" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}));

// The window has its own tests: here, a command said in it, and what it opens with.
vi.mock("./pet-chat", async () => {
  const { petAction } = await import("@/lib/pet-actions");
  return {
    PetChat: ({
      side,
      onClose,
      onCommand,
      draft,
      modelReady,
    }: {
      side: string;
      onClose: () => void;
      onCommand: (action: unknown, said: string) => void;
      draft?: string;
      modelReady: boolean;
    }) => (
      <div role="dialog" data-side={side} data-draft={draft} data-model-ready={modelReady}>
        <button onClick={onClose}>close window</button>
        <button onClick={() => onCommand(petAction("vocab_review"), "flashcards")}>
          say flashcards
        </button>
      </div>
    ),
  };
});

const advice = vi.hoisted(() => ({ current: null as Advice | null }));
vi.mock("@/lib/pet-nudges", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/pet-nudges")>()),
  usePetAdvice: () => ({ advice: advice.current, plan: null, reload: () => {} }),
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
  nav.search = "";
  advice.current = null;
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
  it("is not there when the learner turned it off, or before the assistant is known", () => {
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
    expect(screen.getByRole("img", { name: "Max, your assistant" })).toHaveAttribute("data-animate", "false");
  });

  it("tells the pages to leave room for it while it shows (task 73.6)", async () => {
    const { unmount } = show();
    expect(document.documentElement.dataset.pet).toBe("full");
    await userEvent.click(screen.getByRole("button", { name: "Collapse the desk pet" }));
    expect(document.documentElement.dataset.pet).toBe("collapsed");
    unmount();
    expect(document.documentElement.dataset.pet).toBeUndefined();
  });

  it("keeps above the chat input box on the chat page (task 73.6)", () => {
    nav.pathname = "/chat";
    const composer = document.createElement("div");
    composer.setAttribute("data-chat-composer", "");
    composer.getBoundingClientRect = () => ({ top: 700 }) as DOMRect;
    document.body.append(composer);
    try {
      show();
      // 800 high window, box top at 700: 100 below it, plus an 8px gap.
      expect(screen.getByTestId("tutor-pet").style.bottom).toContain("108px");
    } finally {
      composer.remove();
    }
  });

  it("does not move for the input box on other pages", () => {
    show();
    expect(screen.getByTestId("tutor-pet").style.bottom).toContain(", 0px,");
  });

  it("collapses to a small button and comes back, remembered on this device", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Collapse the desk pet" }));
    expect(stored().collapsed).toBe(true);
    expect(screen.getByTestId("tutor-pet").style.right).toBe("0px");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show Max, your desk pet" }));
    expect(stored().collapsed).toBe(false);
    expect(screen.getByRole("img", { name: "Max, your assistant" })).toBeInTheDocument();
  });

  it("is dragged to the nearer edge, at the height it was dropped", () => {
    show();
    const pet = screen.getByTestId("tutor-pet");
    pet.getBoundingClientRect = () => new DOMRect(900, 600, 88, 88);
    fireEvent.pointerDown(pet, { button: 0, pointerId: 1, clientX: 940, clientY: 640 });
    // A quick drag is off the pet's box at once: the page hears the rest of it.
    fireEvent.pointerMove(document.body, { pointerId: 1, clientX: 700, clientY: 640 });
    // Still on the right half while moving: it follows the pointer.
    expect(pet.style.left).toBe("660px");
    fireEvent.pointerMove(document.body, { pointerId: 1, clientX: 200, clientY: 340 });
    fireEvent.pointerUp(document.body, { pointerId: 1, clientX: 200, clientY: 340 });

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
      const avatar = () => screen.getByRole("img", { name: "Max, your assistant" });
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

  it("asks about a command in a bubble, and opens the window again to ask the assistant", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    await userEvent.click(screen.getByRole("button", { name: "say flashcards" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const bubble = screen.getByTestId("pet-bubble");
    expect(bubble).toHaveAttribute("data-key", "ask:vocab_review");
    expect(screen.getByRole("status")).toHaveTextContent("Start your flashcards?");
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute("href", "/vocab/review");

    await userEvent.click(screen.getByRole("button", { name: "Ask Max instead" }));
    expect(screen.queryByTestId("pet-bubble")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveAttribute("data-draft", "flashcards");
    // Closed and opened again: an empty input box.
    await userEvent.click(screen.getByRole("button", { name: "close window" }));
    await userEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    expect(screen.getByRole("dialog")).not.toHaveAttribute("data-draft");
  });

  it("tells the window whether a chat model is set up", async () => {
    advice.current = { model_ready: false, items: [] };
    show();
    await userEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    expect(screen.getByRole("dialog")).toHaveAttribute("data-model-ready", "false");
  });

  it("makes way when flashcards open or the page changes", async () => {
    const view = show();
    const rerender = () =>
      view.rerender(
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <TutorPet />
        </NextIntlClientProvider>,
      );
    await userEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    nav.search = "review=all";
    rerender();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    nav.search = "";
    rerender();
    await userEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    await userEvent.click(screen.getByRole("button", { name: "say flashcards" }));
    expect(screen.getByTestId("pet-bubble")).toBeInTheDocument();
    nav.pathname = "/learner";
    rerender();
    expect(screen.queryByTestId("pet-bubble")).not.toBeInTheDocument();
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

describe("TutorPet reminders", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetPet(); // awake: an earlier test left it dozing
  });
  afterEach(() => vi.useRealTimers());
  const settle = () => act(() => vi.advanceTimersByTime(SETTLE_MS));

  it("says in a bubble what to do first, once settled on a page", () => {
    advice.current = { model_ready: false, items: [] };
    show();
    expect(screen.queryByTestId("pet-bubble")).toBeNull();
    settle();
    expect(screen.getByTestId("pet-bubble")).toHaveAttribute("data-key", "nudge:setup_model");
    expect(screen.getByRole("status")).toHaveTextContent("I don't have a chat model");
    expect(screen.getByRole("link", { name: "Open settings" })).toHaveAttribute(
      "href",
      "/settings#connections",
    );
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.queryByTestId("pet-bubble")).toBeNull();
    // Said today: not again, here or after a while.
    act(() => vi.advanceTimersByTime(60 * 60_000));
    expect(screen.queryByTestId("pet-bubble")).toBeNull();
  });

  it("says nothing when the learner turned reminders off, or while the window is open", () => {
    advice.current = { model_ready: false, items: [] };
    tutor.current = { ...tutor.current!, nudges: false };
    const view = show();
    settle();
    expect(screen.queryByTestId("pet-bubble")).toBeNull();

    tutor.current = { ...tutor.current, nudges: true };
    view.rerender(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <TutorPet />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Chat with Max" }));
    settle();
    expect(screen.queryByTestId("pet-bubble")).toBeNull();
  });

  it("collapsed, keeps it for when it is opened, with a dot", () => {
    advice.current = { model_ready: false, items: [] };
    show();
    fireEvent.click(screen.getByRole("button", { name: "Collapse the desk pet" }));
    settle();
    expect(screen.queryByTestId("pet-bubble")).toBeNull();
    expect(screen.getByTestId("tutor-pet-dot")).toHaveTextContent("Max has something to say");
    fireEvent.click(screen.getByRole("button", { name: "Show Max, your desk pet" }));
    expect(screen.getByTestId("pet-bubble")).toHaveAttribute("data-key", "nudge:setup_model");
  });

  it("welcomes the learner back from a doze", () => {
    advice.current = { model_ready: false, items: [] };
    show();
    act(() => checkSleep(Date.now() + SLEEP_AFTER_MS));
    settle();
    expect(screen.queryByTestId("pet-bubble")).toBeNull(); // not while it dozes
    act(() => petActivity());
    expect(screen.getByRole("status")).toHaveTextContent(/^Welcome back! I don't have a chat model/);
  });

  it("after a round of flashcards, offers the new words", () => {
    advice.current = { model_ready: true, items: [] };
    const view = show();
    act(() => announceReviewed());
    advice.current = {
      model_ready: true,
      items: [
        {
          candidate_id: "l",
          kind: "vocab_learn",
          count: 7,
          days_since: null,
          in_progress: false,
          reason: null,
          level: null,
          learned: null,
          total: null,
          kc: null,
          p_mastery: null,
          book: null,
        },
      ],
    };
    view.rerender(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <TutorPet />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("All reviewed! 7 new words left");
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/vocab/review?mode=new",
    );
  });

  it("cheers when today's plan is done", () => {
    advice.current = { model_ready: true, items: [] };
    show();
    act(() => petPlanDone("2026-10-14"));
    expect(screen.getByRole("status")).toHaveTextContent("Today's plan is all done");
    expect(screen.queryByTestId("pet-bubble-action")).toBeNull();
  });
});
