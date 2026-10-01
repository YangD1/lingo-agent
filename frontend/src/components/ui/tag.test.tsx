import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CefrTag, isCefrLevel } from "./tag";

describe("CefrTag", () => {
  it("fills one step of the scale per level reached", () => {
    render(<CefrTag level="B2" />);
    const tag = screen.getByTestId("cefr-tag");
    expect(tag).toHaveTextContent("B2");
    const steps = tag.querySelectorAll("[data-filled]");
    expect(steps).toHaveLength(6);
    expect(tag.querySelectorAll('[data-filled="true"]')).toHaveLength(4);
  });

  it("recognises CEFR levels", () => {
    expect(isCefrLevel("C1")).toBe(true);
    expect(isCefrLevel("D1")).toBe(false);
  });
});
