import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Profile } from "@/lib/types";

import en from "../../../messages/en.json";
import { LanguageSwitch } from "./language-switch";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const profile = (over: Partial<Profile>): Profile => ({
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
  ...over,
});

function show() {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <LanguageSwitch />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
});

describe("LanguageSwitch", () => {
  it("shows the level's pick, and saves the learner's choice", async () => {
    api
      .mockResolvedValueOnce(profile({}))
      .mockResolvedValueOnce(profile({ chat_language: "en", chat_language_effective: "en" }));
    show();
    const chinese = await screen.findByRole("radio", { name: "Mostly Chinese" });
    expect(chinese).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/Picked by your level/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "Mostly English" }));
    expect(api).toHaveBeenLastCalledWith("/profile", {
      method: "PATCH",
      json: { chat_language: "en" },
    });
    expect(screen.getByRole("radio", { name: "Mostly English" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(await screen.findByText("From the next reply")).toBeInTheDocument();
  });

  it("does nothing for the language already in use", async () => {
    api.mockResolvedValueOnce(profile({ chat_language: "en", chat_language_effective: "en" }));
    show();
    await userEvent.click(await screen.findByRole("radio", { name: "Mostly English" }));
    expect(api).toHaveBeenCalledTimes(1);
  });

  it("moves back and says why when saving fails", async () => {
    api
      .mockResolvedValueOnce(profile({}))
      .mockRejectedValueOnce(new ApiError(500, "internal_error", "boom"));
    show();
    await userEvent.click(await screen.findByRole("radio", { name: "Mostly English" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("radio", { name: "Mostly Chinese" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("stays hidden until the profile is known", () => {
    api.mockImplementation(() => new Promise(() => {}));
    show();
    expect(screen.queryByTestId("chat-language")).not.toBeInTheDocument();
  });
});
