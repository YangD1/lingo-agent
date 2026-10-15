import { describe, expect, it } from "vitest";

import { placeTestOuts } from "./message-list";

const at = (time: string | undefined) => ({ createdAt: time });
const quiz = (created_at: string | null) => [{ created_at }];

describe("placeTestOuts (ADR 0044 §5)", () => {
  const messages = [
    at("2026-10-15T08:00:00Z"),
    at("2026-10-15T08:00:05Z"),
    at("2026-10-15T09:00:00Z"),
    at("2026-10-15T09:00:04Z"),
  ];

  it("puts a quiz before the first message after it", () => {
    const placed = placeTestOuts(messages, {
      "test-out-a": quiz("2026-10-15T08:30:00.123456+00:00"),
      u1: quiz("2026-10-15T08:00:01Z"), // a turn's card: under its message, not placed here
    });
    expect([...placed]).toEqual([[2, ["test-out-a"]]]);
  });

  it("puts a quiz newer than every message, or with no time, at the end, oldest first", () => {
    const placed = placeTestOuts(messages, {
      "test-out-b": quiz(null),
      "test-out-a": quiz("2026-10-15T10:00:00Z"),
    });
    expect([...placed]).toEqual([[4, ["test-out-a", "test-out-b"]]]);
  });

  it("passes over messages saved before stamps", () => {
    const placed = placeTestOuts([at(undefined), at(undefined), at("2026-10-15T09:00:00Z")], {
      "test-out-a": quiz("2026-10-15T08:00:00Z"),
    });
    expect([...placed]).toEqual([[2, ["test-out-a"]]]);
  });

  it("shows a quiz in a conversation with nothing else", () => {
    expect([...placeTestOuts([], { "test-out-a": quiz("2026-10-15T08:00:00Z") })]).toEqual([
      [0, ["test-out-a"]],
    ]);
  });
});
