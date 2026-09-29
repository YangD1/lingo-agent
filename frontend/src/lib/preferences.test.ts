import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useShowActivity } from "./preferences";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useShowActivity", () => {
  it("is on by default and remembers being turned off", () => {
    const { result } = renderHook(() => useShowActivity());
    expect(result.current[0]).toBe(true);

    act(() => result.current[1](false));

    expect(result.current[0]).toBe(false);
    expect(renderHook(() => useShowActivity()).result.current[0]).toBe(false);
  });

  it("still applies on this page when storage refuses it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const { result } = renderHook(() => useShowActivity());

    act(() => result.current[1](false));

    expect(result.current[0]).toBe(false);
    act(() => result.current[1](true)); // leave the module-level fallback as found
  });
});
