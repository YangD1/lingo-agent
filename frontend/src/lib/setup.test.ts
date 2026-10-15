import { describe, expect, it } from "vitest";

import { initialView, nextView, previousView, stepNumber, unsetSteps } from "./setup";

describe("setup guide steps", () => {
  it("starts where a link points, or at the top", () => {
    expect(initialView("model")).toBe("model");
    expect(initialView(undefined)).toBe("profile");
    expect(initialView("done")).toBe("profile");
    expect(initialView("nonsense")).toBe("profile");
  });

  it("walks the five steps to the summary and back", () => {
    expect(nextView("profile")).toBe("model");
    expect(nextView("placement")).toBe("done");
    expect(nextView("done")).toBe("done");
    expect(previousView("profile")).toBeNull();
    expect(previousView("model")).toBe("profile");
    expect(previousView("done")).toBe("placement");
    expect(stepNumber("goals")).toBe(3);
  });

  it("lists what is left to set up, in order", () => {
    expect(
      unsetSteps({ profile: true, model: false, goals: true, tutor: false, placement: false }),
    ).toEqual(["model", "tutor", "placement"]);
  });
});
