import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JOY_MS } from "@/components/tutor/avatar-state";

import {
  checkSleep,
  petActivity,
  petHappy,
  petHold,
  petPlanDone,
  petState,
  resetPet,
  SLEEP_AFTER_MS,
  usePetHold,
  usePetState,
} from "./tutor-pet";
import { setLevelSource } from "./voice-level";

beforeEach(() => {
  vi.useFakeTimers();
  resetPet();
});

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("the desk pet's state", () => {
  it("listens over speaking over thinking over happy", () => {
    const think = petHold("thinking");
    expect(petState()).toBe("thinking");
    petHappy();
    expect(petState()).toBe("thinking");
    const quiet = setLevelSource(() => 0.5);
    expect(petState()).toBe("speaking");
    const listen = petHold("listening");
    expect(petState()).toBe("listening");

    listen();
    listen(); // twice: still only one let go
    quiet();
    think();
    expect(petState()).toBe("happy");
  });

  it("holds while anyone holds", () => {
    const one = petHold("listening");
    const two = petHold("listening");
    one();
    expect(petState()).toBe("listening");
    two();
    expect(petState()).toBe("idle");
  });

  it("hops once: what comes during a hop is dropped", () => {
    petHappy();
    vi.advanceTimersByTime(JOY_MS - 100);
    petHappy(); // dropped, not extending the hop
    vi.advanceTimersByTime(100);
    expect(petState()).toBe("idle");
    petHappy();
    expect(petState()).toBe("happy");
  });

  it("dozes after three minutes alone, and wakes on any activity", () => {
    const start = Date.now();
    petActivity(start);
    checkSleep(start + SLEEP_AFTER_MS - 1);
    expect(petState()).toBe("idle");
    checkSleep(start + SLEEP_AFTER_MS);
    expect(petState()).toBe("sleeping");

    petActivity(start + SLEEP_AFTER_MS + 5);
    expect(petState()).toBe("idle");
  });

  it("doesn't doze while something is going on, and wakes when it starts", () => {
    const start = Date.now();
    petActivity(start);
    const listen = petHold("listening");
    checkSleep(start + SLEEP_AFTER_MS * 2);
    expect(petState()).toBe("listening");
    listen();
    // The wait starts over from when it last had something to do.
    checkSleep(start + SLEEP_AFTER_MS * 2 + 1000);
    expect(petState()).toBe("idle");

    checkSleep(start + SLEEP_AFTER_MS * 4);
    expect(petState()).toBe("sleeping");
    const quiet = setLevelSource(() => 0);
    expect(petState()).toBe("speaking");
    quiet();
    petHold("thinking")();
    expect(petState()).toBe("idle"); // the hold woke it
  });

  it("cheers today's plan once a day on this device", () => {
    petPlanDone("2026-10-13");
    expect(petState()).toBe("happy");
    vi.advanceTimersByTime(JOY_MS);
    petPlanDone("2026-10-13");
    expect(petState()).toBe("idle");
    petPlanDone("2026-10-14");
    expect(petState()).toBe("happy");
  });
});

describe("hooks", () => {
  it("follow the state, and hold only while active and mounted", () => {
    const state = renderHook(() => usePetState());
    const hold = renderHook(({ on }) => usePetHold("thinking", on), { initialProps: { on: false } });
    expect(state.result.current).toBe("idle");

    hold.rerender({ on: true });
    expect(state.result.current).toBe("thinking");
    hold.unmount();
    expect(state.result.current).toBe("idle");

    let quiet = () => {};
    act(() => {
      quiet = setLevelSource(() => 1);
    });
    expect(state.result.current).toBe("speaking");
    act(() => quiet());
    expect(state.result.current).toBe("idle");
  });

  it("wake on the learner's keys and pointer", () => {
    const state = renderHook(() => usePetState());
    act(() => checkSleep(Date.now() + SLEEP_AFTER_MS));
    expect(state.result.current).toBe("sleeping");
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    });
    expect(state.result.current).toBe("idle");
  });
});
