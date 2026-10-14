import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { DEFAULT_TUTOR, type Tutor, type TutorOptions, resetTutorCache } from "@/lib/tutor";

import en from "../../../messages/en.json";
import { TutorApp } from "./tutor-app";
import { chooseOption } from "@/test/select";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const speech = vi.hoisted(() => ({
  tryServerVoice: vi.fn(() => Promise.resolve()),
  stopSpeaking: vi.fn(),
  useSpeaking: vi.fn(() => false),
}));
vi.mock("@/lib/speech", () => speech);

// jsdom has no 2D canvas; the avatar has its own tests.
vi.mock("./tutor-avatar", () => ({
  TutorAvatar: ({ outfit, fur, label }: { outfit: string; fur: string; label: string }) => (
    <span role={label ? "img" : undefined} aria-label={label} data-outfit={outfit} data-fur={fur} />
  ),
}));

const OPTIONS: TutorOptions = {
  chat: {
    models: ["main:gpt-5-mini", "main:qwen-plus"],
    provided_by: "Ada",
    quota_exhausted: false,
  },
  read_aloud: {
    models: ["main:qwen3-tts-flash"],
    provided_by: "Ada",
    quota_exhausted: false,
    voice_model: "main:qwen3-tts-flash",
    voice_options: [
      { id: "Cherry", name: "Cherry", gender: "female", languages: ["en-US", "en-GB", "zh-CN"], accent: null, note: "" },
      { id: "Ethan", name: "Ethan", gender: "male", languages: ["en-US", "en-GB", "zh-CN"], accent: null, note: "" },
    ],
    default_voices: { "en-US": "Cherry", "en-GB": "Cherry", "zh-CN": "Cherry" },
  },
  realtime: {
    models: ["main:gpt-realtime"],
    provided_by: "Ada",
    quota_exhausted: false,
    voice_options: {
      "main:gpt-realtime": [
        { id: "marin", name: "Marin", gender: null, languages: ["en-US"], accent: null, note: "" },
        { id: "cedar", name: "Cedar", gender: null, languages: ["en-US"], accent: null, note: "" },
      ],
    },
    default_voices: { "main:gpt-realtime": "marin" },
  },
};

let stored: Tutor;
const calls: { method: string; json?: unknown }[] = [];

function serve(options: TutorOptions = OPTIONS) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    if (path === "/tutor/options") return options;
    const method = init?.method ?? "GET";
    if (path !== "/tutor") throw new Error(`unexpected ${path}`);
    calls.push({ method, json: init?.json });
    if (method === "PUT") {
      const body = init!.json as Partial<Tutor>;
      stored = { ...stored, ...body, display_name: body.name ?? "Lingo", unavailable: [] };
    } else if (method === "DELETE") {
      stored = DEFAULT_TUTOR;
      return undefined;
    }
    return stored;
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <TutorApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  speech.tryServerVoice.mockClear();
  resetTutorCache();
  stored = DEFAULT_TUTOR;
  calls.length = 0;
});

describe("TutorApp", () => {
  it("previews looks at once and saves the whole tutor", async () => {
    serve();
    show();
    const save = await screen.findByTestId("tutor-save");
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Name"), "Max");
    await userEvent.click(screen.getByTestId("tutor-outfit-sporty"));
    await userEvent.click(screen.getByRole("button", { name: "Blue grey" }));
    await userEvent.click(screen.getByRole("switch", { name: /Desk pet/ }));
    const preview = screen.getByRole("img", { name: "Preview of Max" });
    expect(preview).toHaveAttribute("data-outfit", "sporty");
    expect(preview).toHaveAttribute("data-fur", "#829cb8");

    await chooseOption(userEvent, screen.getByLabelText("Model"), "qwen-plus · main");
    await chooseOption(userEvent, screen.getByLabelText("American"), /^Ethan/);
    await chooseOption(userEvent, screen.getByLabelText("Voice"), /^cedar/i);
    await userEvent.click(save);

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.json).toEqual({
      name: "Max",
      avatar: "sporty",
      color: "#829cb8",
      animate: true,
      pet: false,
      chat_model: "main:qwen-plus",
      tts_model: "main:qwen3-tts-flash",
      voices: { "en-US": "Ethan" },
      // Following the settings page pins the call model the voice belongs to.
      realtime_model: "main:gpt-realtime",
      realtime_voice: "cedar",
    });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(save).toBeDisabled();
  });

  it("tells a member whose models they use", async () => {
    serve();
    show();
    const chat = await screen.findByTestId("tutor-chat");
    expect(within(chat).getByTestId("tutor-provided-by")).toHaveTextContent("Provided by Ada");
    expect(within(chat).getByRole("combobox", { name: "Model" })).toHaveTextContent(
      "Follow settings (now: gpt-5-mini · main)",
    );
  });

  it("tries a voice before it is saved", async () => {
    serve();
    show();
    await chooseOption(userEvent, await screen.findByLabelText("Chinese"), /^Ethan/);
    await userEvent.click(screen.getByTestId("tutor-try-zh-CN"));
    expect(speech.tryServerVoice).toHaveBeenCalledWith(
      "tutor-voice-try",
      "你好，我是Lingo。我们一起练英语吧！",
      "zh-CN",
      "Ethan",
    );
    // Not chosen: the voice used now.
    await userEvent.click(screen.getByTestId("tutor-try-en-US"));
    expect(speech.tryServerVoice).toHaveBeenLastCalledWith(
      "tutor-voice-try",
      expect.stringContaining("Hi, I'm Lingo"),
      "en-US",
      "Cherry",
    );
  });

  it("says when a saved choice can't be used any more", async () => {
    stored = { ...DEFAULT_TUTOR, chat_model: "gone:model", unavailable: ["chat_model"] };
    serve();
    show();
    const chat = await screen.findByTestId("tutor-chat");
    expect(within(chat).getByTestId("tutor-dropped")).toHaveTextContent("gpt-5-mini · main is used instead");
    expect(within(chat).getByLabelText("Model")).toHaveValue("");
  });

  it("without server read-aloud or calls, points to the settings page", async () => {
    serve({
      ...OPTIONS,
      read_aloud: { ...OPTIONS.read_aloud, models: [], voice_model: null, voice_options: [], default_voices: {} },
      realtime: { ...OPTIONS.realtime, models: [], voice_options: {}, default_voices: {} },
    });
    show();
    const voices = await screen.findByTestId("tutor-voices");
    expect(within(voices).getByText(/this device's own voices/)).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-call")).not.toBeInTheDocument();
  });

  it("resets to the defaults after asking", async () => {
    stored = { ...DEFAULT_TUTOR, name: "Max", display_name: "Max" };
    serve();
    show();
    expect(await screen.findByLabelText("Name")).toHaveValue("Max");
    await userEvent.click(screen.getByTestId("tutor-reset"));
    await userEvent.click(await screen.findByRole("button", { name: "Reset to default" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(screen.getByLabelText("Name")).toHaveValue("");
  });

  it("shows why it can't load", async () => {
    api.mockRejectedValue(new ApiError(0, "network_error", "network request failed"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server");
    expect(screen.getByRole("heading", { name: "My tutor" })).toBeInTheDocument();
  });
});
