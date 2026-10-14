import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LandingBackdrop } from "@/components/home/landing-backdrop";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));

// The real module needs WebGPU; stand in a marker that records its props.
vi.mock("@/components/home/landing-shaders", () => ({
  SilkShader: ({ dark, still }: { dark: boolean; still: boolean }) => (
    <div data-testid="shader" data-dark={dark} data-still={still} />
  ),
  InkShader: () => <div data-testid="shader" />,
}));

function setGpu(present: boolean) {
  if (present) Object.defineProperty(navigator, "gpu", { value: {}, configurable: true });
  else Reflect.deleteProperty(navigator, "gpu");
}

/** jsdom has no matchMedia; this one answers the reduced-motion query. */
function setReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", () => ({
    matches: reduce,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe("LandingBackdrop", () => {
  afterEach(() => {
    setGpu(false);
    vi.unstubAllGlobals();
  });

  it("keeps only the CSS fallback when the browser has no WebGPU", () => {
    setGpu(false);
    setReducedMotion(false);
    const { container } = render(<LandingBackdrop scene="silk" />);
    expect(container.firstChild).toHaveClass("landing-silk");
    expect(container.firstChild).toHaveAttribute("aria-hidden");
    expect(screen.queryByTestId("shader")).toBeNull();
  });

  it("loads the shader with WebGPU, following the theme and reduced motion", async () => {
    setGpu(true);
    setReducedMotion(true);
    render(<LandingBackdrop scene="silk" />);
    const shader = await screen.findByTestId("shader");
    expect(shader).toHaveAttribute("data-dark", "true");
    expect(shader).toHaveAttribute("data-still", "true");
  });
});
