import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { SetupState, SetupView } from "@/lib/setup";
import type { Connection, Profile, User } from "@/lib/types";
import { DEFAULT_TUTOR } from "@/lib/tutor";
import { chooseOption } from "@/test/select";

import en from "../../../messages/en.json";
import { SetupApp } from "./setup-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
const router = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
// jsdom has no 2D canvas; the avatar has its own tests.
vi.mock("@/components/tutor/tutor-avatar", () => ({
  TutorAvatar: ({ outfit, label }: { outfit: string; label: string }) => (
    <span role={label ? "img" : undefined} aria-label={label} data-outfit={outfit} />
  ),
}));

const USER: User = { id: "u1", email: "lee@example.com", display_name: null, setup_completed_at: null };
const NOTHING = { profile: false, model: false, goals: false, tutor: false, placement: false };
const PROFILE: Profile = {
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
const PRESETS = {
  allow_private_networks: false,
  presets: [
    { name: "deepseek", kind: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", models: ["deepseek-chat"] },
    { name: "azure", kind: "azure_speech", label: "Azure", base_url: "https://x", models: [] },
    { name: "groq", kind: "openai_compatible", label: "Groq", base_url: "https://x", models: [] },
  ],
};
const connection = (patch: Partial<Connection> = {}): Connection => ({
  id: "c1",
  name: "deepseek",
  kind: "deepseek",
  base_url: "https://api.deepseek.com",
  has_api_key: true,
  key_hint: "…abcd",
  params: {},
  enabled: true,
  default_model: null,
  last_verified_at: null,
  last_error: null,
  ...patch,
});

type Call = { path: string; method: string; json?: unknown };
let calls: Call[];
let state: SetupState;
let profile: Profile;
// What listing the connection's models answers: ids, or an error.
let models: string[] | Error;

function serve() {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    const method = init?.method ?? "GET";
    calls.push({ path, method, json: init?.json });
    const json = init?.json as Record<string, unknown> | undefined;
    switch (`${method} ${path}`) {
      case "GET /me/setup":
        return state;
      case "POST /me/setup/complete":
        state = { ...state, completed_at: "2026-10-15T10:00:00Z" };
        return state;
      case "PATCH /auth/me":
        state = { ...state, steps: { ...state.steps, profile: true } };
        return { ...USER, display_name: json?.display_name };
      case "GET /profile":
        return profile;
      case "PATCH /profile":
        profile = { ...profile, ...json };
        return profile;
      case "GET /provider-presets":
        return PRESETS;
      case "GET /tenant/connections":
        return [];
      case "POST /tenant/connections":
        return connection();
      case "PATCH /tenant/connections/c1":
        if (json?.default_model) state = { ...state, steps: { ...state.steps, model: true } };
        return connection({ default_model: (json?.default_model as string) ?? null });
      case "GET /tenant/connections/c1/models":
        if (models instanceof Error) throw models;
        return { models: models.map((id) => ({ id, category: "chat" })) };
      case "GET /tutor":
        return DEFAULT_TUTOR;
      case "GET /tutor/options":
        return {
          chat: { models: [], provided_by: null, quota_exhausted: false },
          read_aloud: { models: [], provided_by: null, quota_exhausted: false, voice_model: null, voice_options: [], default_voices: {} },
          realtime: { models: [], provided_by: null, quota_exhausted: false, voice_options: {}, default_voices: {} },
        };
      case "PUT /tutor":
        return { ...DEFAULT_TUTOR, ...json, display_name: json?.name ?? "JOJO" };
    }
    throw new Error(`unexpected ${method} ${path}`);
  });
}

const writes = () => calls.filter((c) => c.method !== "GET");

function show(initial: SetupView = "profile", user: User = USER) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SetupApp user={user} initial={initial} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  router.replace.mockReset();
  calls = [];
  state = { completed_at: null, steps: { ...NOTHING } };
  profile = { ...PROFILE };
  models = ["deepseek-chat", "deepseek-reasoner"];
  serve();
});

describe("SetupApp", () => {
  it("saves the name and language, takes the device's time zone, and moves on", async () => {
    const user = userEvent.setup();
    show();
    await user.type(await screen.findByLabelText("What should we call you?"), "Lee");
    await user.click(screen.getByRole("radio", { name: "Chinese" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Connect a chat model" })).toBeInTheDocument();
    expect(writes()).toEqual([
      { path: "/auth/me", method: "PATCH", json: { display_name: "Lee" } },
      {
        path: "/profile",
        method: "PATCH",
        json: { explanation_language: "zh", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      },
    ]);
    expect(screen.getByTestId("setup-dot-profile")).toHaveAttribute("data-set", "true");
  });

  it("skips everything at once on a new account", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Skip all and look around" }));
    expect(api).toHaveBeenCalledWith("/me/setup/complete", { method: "POST" });
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("asks before skipping the model, and stays when told to go back", async () => {
    const user = userEvent.setup();
    show("model");
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    expect(screen.getByRole("alertdialog", { name: "Skip the model for now?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect a model" }));
    expect(screen.getByRole("heading", { name: "Connect a chat model" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Skip" }));
    await user.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(await screen.findByRole("heading", { name: "What are you learning for?" })).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("offers chat providers only, connects with a key and picks a model", async () => {
    const user = userEvent.setup();
    show("model");
    const provider = await screen.findByLabelText("Provider");
    await user.click(provider);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["DeepSeek"]);
    await user.keyboard("{Escape}");
    await user.type(screen.getByLabelText("API key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByTestId("setup-model-ready")).toHaveTextContent(
      "Connected to DeepSeek, using deepseek-chat by default.",
    );
    expect(writes()).toEqual([
      { path: "/tenant/connections", method: "POST", json: { preset: "deepseek", api_key: "sk-test" } },
      { path: "/tenant/connections/c1", method: "PATCH", json: { default_model: "deepseek-chat" } },
    ]);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: "What are you learning for?" })).toBeInTheDocument();
    expect(screen.getByTestId("setup-dot-model")).toHaveAttribute("data-set", "true");
  });

  it("says why a key failed, and retries on the same connection", async () => {
    const user = userEvent.setup();
    models = new ApiError(502, "model_list_failed", "HTTP 401: invalid key");
    show("model");
    await user.type(await screen.findByLabelText("API key"), "wrong");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't connect: HTTP 401: invalid key.");

    models = ["deepseek-chat"];
    await user.clear(screen.getByLabelText("API key"));
    await user.type(screen.getByLabelText("API key"), "right");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByTestId("setup-model-ready")).toBeInTheDocument();
    expect(writes().map((c) => [c.method, c.path, c.json])).toEqual([
      ["POST", "/tenant/connections", { preset: "deepseek", api_key: "wrong" }],
      ["PATCH", "/tenant/connections/c1", { api_key: "right" }],
      ["PATCH", "/tenant/connections/c1", { default_model: "deepseek-chat" }],
    ]);
  });

  it("sends only the goals the learner changed", async () => {
    const user = userEvent.setup();
    profile = { ...PROFILE, interests: ["films"] };
    show("goals");
    await user.click(await screen.findByRole("radio", { name: "20 min" }));
    await chooseOption(user, screen.getByLabelText("Target exam"), "IELTS");
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Name your assistant" })).toBeInTheDocument();
    expect(writes()).toEqual([
      { path: "/profile", method: "PATCH", json: { target_exam: "ielts", daily_minutes: 20 } },
    ]);
  });

  it("names the assistant, and saves nothing when left as is", async () => {
    const user = userEvent.setup();
    show("tutor");
    await user.click(await screen.findByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: "Check your current level" })).toBeInTheDocument();
    expect(writes()).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.type(await screen.findByLabelText("Name"), "Momo");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: "Check your current level" });
    expect(writes()).toEqual([
      expect.objectContaining({ path: "/tutor", method: "PUT", json: expect.objectContaining({ name: "Momo" }) }),
    ]);
  });

  it("starting the test finishes the guide first", async () => {
    show("placement");
    await userEvent.click(await screen.findByRole("button", { name: "Finish setup and start the test" }));
    expect(api).toHaveBeenCalledWith("/me/setup/complete", { method: "POST" });
    expect(router.replace).toHaveBeenCalledWith("/placement");
  });

  it("sums up what's set, and a 'later' link finishes before leaving", async () => {
    const user = userEvent.setup();
    state = { completed_at: null, steps: { ...NOTHING, profile: true, goals: true } };
    show("placement");
    await user.click(await screen.findByRole("button", { name: "Skip" }));

    const summary = await screen.findByTestId("setup-summary");
    const model = within(summary).getByText("Model").closest("li")!;
    expect(model).toHaveAttribute("data-set", "false");
    expect(within(summary).getByText("Goals").closest("li")).toHaveAttribute("data-set", "true");
    expect(within(summary).getAllByRole("link", { name: "Set up later" })).toHaveLength(3);
    await user.click(within(model).getByRole("link", { name: "Set up later" }));
    expect(api).toHaveBeenCalledWith("/me/setup/complete", { method: "POST" });
    expect(router.replace).toHaveBeenCalledWith("/settings#connections");
  });

  it("re-entered: ticks what's set, prefills, offers no 'skip all', and saves nothing unchanged", async () => {
    const user = userEvent.setup();
    state = {
      completed_at: "2026-10-01T00:00:00Z",
      steps: { profile: true, model: true, goals: false, tutor: false, placement: true },
    };
    profile = { ...PROFILE, explanation_language: "en", timezone: "Asia/Shanghai" };
    show("profile", { ...USER, display_name: "Lee", setup_completed_at: "2026-10-01T00:00:00Z" });

    expect(await screen.findByLabelText("What should we call you?")).toHaveValue("Lee");
    expect(await screen.findByRole("radio", { name: "English" })).toBeChecked();
    expect(screen.queryByRole("button", { name: "Skip all and look around" })).not.toBeInTheDocument();
    expect(screen.getByTestId("setup-dot-model")).toHaveAttribute("data-set", "true");
    expect(screen.getByTestId("setup-dot-goals")).not.toHaveAttribute("data-set");

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByTestId("setup-model-ready")).toHaveTextContent("A chat model is ready");
    expect(writes()).toEqual([]);
  });
});
