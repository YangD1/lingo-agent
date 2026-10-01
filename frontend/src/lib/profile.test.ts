import { describe, expect, it } from "vitest";

import { parseInterests, profileChanges, toForm } from "./profile";
import type { Profile } from "./types";

const empty: Profile = {
  native_language: null,
  occupation: null,
  goal: null,
  target_exam: null,
  interests: [],
  daily_minutes: null,
  explanation_language: null,
  chat_language: null,
  chat_language_effective: "zh",
  cefr_level: null,
  timezone: null,
  manual_fields: [],
};

describe("parseInterests", () => {
  it("splits on ASCII and full-width commas and 、, dropping blanks and duplicates", () => {
    expect(parseInterests(" travel, films，旅行、 travel ,, ")).toEqual(["travel", "films", "旅行"]);
  });
});

describe("profileChanges", () => {
  it("sends nothing when nothing changed", () => {
    const saved: Profile = { ...empty, occupation: "nurse", interests: ["jazz"], daily_minutes: 20 };
    expect(profileChanges(saved, toForm(saved))).toEqual({});
  });

  it("sends only changed fields, with their API types", () => {
    const form = { ...toForm(empty), occupation: " nurse ", daily_minutes: "30", interests: "a, b" };
    expect(profileChanges(empty, form)).toEqual({
      occupation: "nurse",
      daily_minutes: 30,
      interests: ["a", "b"],
    });
  });

  it("clears a field emptied by the learner", () => {
    const saved: Profile = { ...empty, goal: "Pass IELTS", target_exam: "ielts", interests: ["x"] };
    const form = { ...toForm(saved), goal: "  ", target_exam: "", interests: "" };
    expect(profileChanges(saved, form)).toEqual({ goal: null, target_exam: null, interests: [] });
  });

  it("sends the tutor's language, and null to go back to picking it by level", () => {
    expect(profileChanges(empty, { ...toForm(empty), chat_language: "en" })).toEqual({
      chat_language: "en",
    });
    const chosen: Profile = { ...empty, chat_language: "en", chat_language_effective: "en" };
    expect(profileChanges(chosen, { ...toForm(chosen), chat_language: "" })).toEqual({
      chat_language: null,
    });
  });
});
