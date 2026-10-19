import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection, ReasoningLevel, TaskRoute } from "@/lib/types";

import en from "../../../messages/en.json";
import { RouteSection, type RouteTask, levelOf, savedReasoning } from "./route-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const route = (overrides: Partial<TaskRoute>): TaskRoute => ({
  section: "llm",
  task: "chat",
  models: [],
  params: {},
  disabled: [],
  overridden: false,
  effective: [],
  effective_source: null,
  ...overrides,
});

const ROUTES: TaskRoute[] = [
  route({ task: "chat", effective: ["relay:chat-model"], effective_source: "auto" }),
  route({ task: "reflect" }),
  // Vision has no automatic fallback (ADR 0008 §5): nothing configured, nothing runs.
  route({ task: "vision" }),
  route({
    section: "asr",
    task: "default",
    models: ["groq:whisper-large-v3-turbo"],
    overridden: true,
    effective: ["groq:whisper-large-v3-turbo"],
    effective_source: "override",
  }),
];

const RELAY: Connection = {
  id: "c1",
  name: "relay",
  kind: "openai_compatible",
  base_url: "https://relay.example.com/v1",
  has_api_key: true,
  key_hint: "…1234",
  params: {},
  enabled: true,
  default_model: "chat-model",
  last_verified_at: null,
  last_error: null,
};

function show(task: RouteTask, connections: Connection[] = []) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RouteSection task={task} connections={connections} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? ROUTES : undefined));
});

describe("RouteSection", () => {
  it("says when the vision route is not set up", async () => {
    show("vision");

    expect(await screen.findByTestId("route-source-vision")).toHaveTextContent(
      "Not set up: images and scanned PDFs can't be read",
    );
    expect(screen.getByText("Image model (vision)")).toBeInTheDocument();
  });

  it("edits the asr section's single route", async () => {
    show("asr");

    expect(await screen.findByRole("list", { name: "Speech-to-text" })).toHaveTextContent(
      "groq:whisper-large-v3-turbo",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/asr/default", { method: "DELETE" }),
    );
  });

  it("keeps showing the chat route and where it comes from", async () => {
    show("chat");

    expect(await screen.findByTestId("route-source-chat")).toHaveTextContent("Automatic");
    expect(screen.getByRole("list", { name: "Chat model" })).toHaveTextContent("relay:chat-model");
  });

  it("sets the background memory model, starting from the connection's chat model", async () => {
    show("reflect", [RELAY]);

    expect(await screen.findByText("Background memory model")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    expect(screen.getByRole("combobox", { name: "Model 1" })).toHaveValue("chat-model");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/llm/reflect", {
        method: "PUT",
        json: { models: ["relay:chat-model"], disabled: [], params: {} },
      }),
    );
  });

  // --- reasoning (task 89.2, per model since task 91) ----------------------------------

  it("sets a model's reasoning at once, keeping the route's other params", async () => {
    const generate = route({
      task: "exercise_generate",
      params: { temperature: 0.7 },
      effective: ["relay:chat-model", "relay:other"],
      effective_source: "default",
      reasoning_options: { "relay:chat-model": ["off", "low", "medium", "high"] },
    });
    api.mockImplementation(async (path: string, init?: { json?: object }) =>
      path === "/tenant/routes"
        ? [...ROUTES, generate]
        : { ...generate, ...init?.json, overridden: true, effective_source: "override" },
    );
    show("exercise_generate", [RELAY]);

    expect(await screen.findByText("Exercise writer")).toBeInTheDocument();
    // Only the models that take a level have the choice.
    expect(screen.queryByRole("combobox", { name: "Reasoning for relay:other" })).toBeNull();
    expect(screen.getByText(/Low is usually enough/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Reasoning for relay:chat-model" }));
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Default", "Off", "Low", "Medium", "High"]);
    await userEvent.click(screen.getByRole("option", { name: "Off" }));

    expect(api).toHaveBeenCalledWith("/tenant/routes/llm/exercise_generate", {
      method: "PUT",
      json: {
        models: ["relay:chat-model", "relay:other"],
        disabled: [],
        params: { temperature: 0.7, reasoning: { "relay:chat-model": "off" } },
      },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "relay:chat-model: reasoning set to Off",
    );

    // Default sends nothing.
    await userEvent.click(screen.getByRole("combobox", { name: "Reasoning for relay:chat-model" }));
    await userEvent.click(await screen.findByRole("option", { name: "Default" }));
    expect(api).toHaveBeenLastCalledWith("/tenant/routes/llm/exercise_generate", {
      method: "PUT",
      json: {
        models: ["relay:chat-model", "relay:other"],
        disabled: [],
        params: { temperature: 0.7 },
      },
    });
  });

  it("reads a single saved level per model, as the backend does", () => {
    const options: Record<string, ReasoningLevel[]> = {
      "relay:gpt": ["low", "medium", "high"],
      "qwen:qwen-plus": ["off", "on"],
    };
    expect(levelOf("low", "relay:gpt", options["relay:gpt"])).toBe("low");
    expect(levelOf("off", "relay:gpt", options["relay:gpt"])).toBe("default");
    expect(levelOf("low", "qwen:qwen-plus", options["qwen:qwen-plus"])).toBe("on");
    expect(levelOf({ "relay:gpt": "high" }, "relay:gpt", options["relay:gpt"])).toBe("high");
    expect(levelOf({ "relay:gpt": "high" }, "qwen:qwen-plus", options["qwen:qwen-plus"])).toBe(
      "default",
    );
    // Only models still in the chain, and only their own levels, are kept.
    expect(savedReasoning("low", options, ["relay:gpt", "qwen:qwen-plus", "relay:plain"])).toEqual({
      "relay:gpt": "low",
      "qwen:qwen-plus": "on",
    });
    expect(savedReasoning({ "relay:gpt": "high", "gone:m": "low" }, options, ["relay:gpt"])).toEqual({
      "relay:gpt": "high",
    });
  });

  it("suggests Low only on the exercise routes, and only for models that take it", async () => {
    const chat = route({
      task: "chat",
      effective: ["relay:chat-model"],
      effective_source: "auto",
      reasoning_options: { "relay:chat-model": ["low", "medium", "high"] },
    });
    const critic = route({
      task: "exercise_critic",
      effective: ["qwen:qwen-plus"],
      effective_source: "default",
      reasoning_options: { "qwen:qwen-plus": ["off", "on"] },
    });
    api.mockImplementation(async (path: string) =>
      path === "/tenant/routes" ? [chat, ...ROUTES.slice(1), critic] : undefined,
    );
    const { unmount } = show("chat", [RELAY]);
    expect(await screen.findByRole("combobox", { name: /^Reasoning for/ })).toBeInTheDocument();
    expect(screen.queryByText(/Low is usually enough/)).not.toBeInTheDocument();
    unmount();

    show("exercise_critic", [RELAY]);
    expect(await screen.findByRole("combobox", { name: /^Reasoning for/ })).toBeInTheDocument();
    expect(screen.queryByText(/Low is usually enough/)).not.toBeInTheDocument();
  });

  it("offers reasoning only on chat model routes", async () => {
    show("asr");
    expect(await screen.findByRole("list", { name: "Speech-to-text" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /^Reasoning for/ })).not.toBeInTheDocument();
  });

  // --- switching models off (ADR 0026) ----------------------------------------------

  it("switches a row off at once, saving the chain that was shown", async () => {
    const OPENAI: Connection = { ...RELAY, id: "c2", name: "openai" };
    const chat = route({
      task: "chat",
      effective: ["relay:a", "openai:b"],
      effective_source: "auto",
    });
    api.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === "/tenant/routes") return [chat];
      if (init?.method === "PUT")
        return route({
          task: "chat",
          models: ["relay:a", "openai:b"],
          disabled: ["relay:a"],
          overridden: true,
          effective: ["openai:b"],
          effective_source: "override",
        });
    });
    show("chat", [RELAY, OPENAI]);

    await userEvent.click(await screen.findByRole("switch", { name: "Use relay:a" }));

    expect(api).toHaveBeenCalledWith("/tenant/routes/llm/chat", {
      method: "PUT",
      json: { models: ["relay:a", "openai:b"], disabled: ["relay:a"], params: {} },
    });
    expect(await screen.findByRole("switch", { name: "Use relay:a" })).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("relay:a is off");
    const [first, second] = screen.getAllByRole("listitem");
    expect(first).toHaveAttribute("data-state", "off");
    expect(first).toHaveTextContent("Off");
    // The first row that runs is the primary now, not a fallback.
    expect(second).toHaveAttribute("data-state", "on");
    expect(second).not.toHaveTextContent("Fallback");
  });

  it("marks rows whose connection is off or gone, and says when nothing is left", async () => {
    const OFF: Connection = { ...RELAY, id: "c2", name: "openai", enabled: false };
    const chat = route({
      task: "chat",
      models: ["relay:a", "openai:b", "gone:c"],
      disabled: ["relay:a"],
      overridden: true,
      effective: [],
      effective_source: null,
    });
    api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? [chat] : undefined));
    show("chat", [RELAY, OFF]);

    expect(await screen.findByText(/Every model here is switched off/)).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-state"))).toEqual([
      "off",
      "connectionOff",
      "connectionMissing",
    ]);
    expect(rows[1]).toHaveTextContent("Connection off");
    expect(rows[2]).toHaveTextContent("Connection deleted");
  });

  it("keeps switched-off rows when the order is edited", async () => {
    const OPENAI: Connection = { ...RELAY, id: "c2", name: "openai" };
    const chat = route({
      task: "chat",
      models: ["relay:a", "openai:b"],
      disabled: ["openai:b"],
      overridden: true,
      effective: ["relay:a"],
      effective_source: "override",
    });
    api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? [chat] : undefined));
    show("chat", [RELAY, OPENAI]);

    await userEvent.click(await screen.findByRole("button", { name: "Edit order" }));
    expect(screen.getByRole("switch", { name: "Use openai:b" })).not.toBeChecked();
    await userEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    await userEvent.click(screen.getByRole("switch", { name: "Use relay:a" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/llm/chat", {
        method: "PUT",
        json: { models: ["openai:b", "relay:a"], disabled: ["openai:b", "relay:a"], params: {} },
      }),
    );
  });

  it("sets up pronunciation assessment on an Azure connection without listing models", async () => {
    const AZURE: Connection = {
      ...RELAY,
      id: "c3",
      name: "azure",
      kind: "azure_speech",
      base_url: "https://eastasia.tts.speech.microsoft.com",
      default_model: null,
    };
    api.mockImplementation(async (path: string) =>
      path === "/tenant/routes"
        ? [...ROUTES, route({ section: "pronunciation", task: "default" })]
        : undefined,
    );
    show("pronunciation", [RELAY, AZURE]);

    expect(await screen.findByTestId("route-source-pronunciation")).toHaveTextContent(
      "Not set up: shadowing compares a transcript instead",
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    // The first row starts on the Azure connection, with its one assessment model.
    expect(screen.getByRole("combobox", { name: "Connection 1" })).toHaveTextContent("azure");
    expect(screen.getByRole("combobox", { name: "Model 1" })).toHaveValue("pronunciation");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/pronunciation/default", {
        method: "PUT",
        json: { models: ["azure:pronunciation"], disabled: [], params: {} },
      }),
    );
    // Nothing asked the vendor for a model list.
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/models"));
  });

  it("lists only a connection's realtime voice models for the realtime route", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/tenant/routes") return [...ROUTES, route({ section: "realtime", task: "default" })];
      if (path === "/tenant/connections/c1/models")
        return {
          models: [
            { id: "chat-model", category: "chat" },
            { id: "gpt-realtime-2.1", category: "other" },
            { id: "qwen3-asr-flash-realtime", category: "other" },
          ],
        };
      return undefined;
    });
    show("realtime", [RELAY]);

    expect(await screen.findByTestId("route-source-realtime")).toHaveTextContent(
      "Not set up: no realtime calls",
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Model 1" }));
    expect(await screen.findByRole("option", { name: "gpt-realtime-2.1" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "chat-model" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "qwen3-asr-flash-realtime" })).not.toBeInTheDocument();
  });

  it("lists every model a Gemini connection offers for the realtime route", async () => {
    // The backend lists only Gemini's Live models, whose names don't say "realtime".
    const gemini: Connection = { ...RELAY, id: "c9", name: "gemini", kind: "gemini" };
    api.mockImplementation(async (path: string) => {
      if (path === "/tenant/routes") return [...ROUTES, route({ section: "realtime", task: "default" })];
      if (path === "/tenant/connections/c9/models")
        return { models: [{ id: "gemini-3.8-live", category: "other" }] };
      return undefined;
    });
    show("realtime", [gemini]);

    await userEvent.click(await screen.findByRole("button", { name: "Edit order" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Model 1" }));
    expect(await screen.findByRole("option", { name: "gemini-3.8-live" })).toBeInTheDocument();
  });

  it("edits a read-aloud route's voices per language, keeping them when a row is switched", async () => {
    const kokoro = "local:speaches-ai/Kokoro-82M-v1.0-ONNX";
    const tts = route({
      section: "tts",
      task: "default",
      models: [kokoro],
      params: { voices: { [kokoro]: { "en-US": "am_adam" } } },
      overridden: true,
      effective: [kokoro],
      effective_source: "override",
      default_voices: { [kokoro]: { "en-US": "af_heart", "en-GB": "bf_emma", "zh-CN": null } },
    });
    const LOCAL = { ...RELAY, name: "local" };
    api.mockImplementation(async (path: string, init?: { json?: unknown }) =>
      path === "/tenant/routes" ? [...ROUTES, tts] : { ...tts, ...(init?.json as object) },
    );
    show("tts", [LOCAL]);

    expect(await screen.findByText("American am_adam")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: `Use ${kokoro}` }));
    expect(api).toHaveBeenCalledWith("/tenant/routes/tts/default", {
      method: "PUT",
      json: {
        models: [kokoro],
        disabled: [kokoro],
        params: { voices: { [kokoro]: { "en-US": "am_adam" } } },
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    const british = screen.getByLabelText("British voice of model 1");
    expect(british).toHaveAttribute("placeholder", "Default: bf_emma");
    expect(screen.getByLabelText("Chinese voice of model 1")).toHaveAttribute(
      "placeholder",
      expect.stringMatching(/^No built-in voice/),
    );
    expect(screen.getByLabelText("American voice of model 1")).toHaveValue("am_adam");
    await userEvent.clear(screen.getByLabelText("American voice of model 1"));
    await userEvent.type(british, "bm_george");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(api).toHaveBeenLastCalledWith("/tenant/routes/tts/default", {
      method: "PUT",
      json: {
        models: [kokoro],
        disabled: [kokoro],
        params: { voices: { [kokoro]: { "en-GB": "bm_george" } } },
      },
    });
  });

  it("offers a model's own voices with who they are, the matching accent first (Q64q)", async () => {
    const flash = "qwen:qwen3-tts-flash";
    const tts = route({
      section: "tts",
      task: "default",
      models: [flash],
      overridden: true,
      effective: [flash],
      effective_source: "override",
      default_voices: { [flash]: { "en-US": "Jennifer", "en-GB": null, "zh-CN": "Cherry" } },
      voice_options: {
        [flash]: [
          {
            id: "Cherry",
            name: "芊悦",
            gender: "female",
            languages: ["en-US", "en-GB", "zh-CN"],
            accent: null,
            note: "sunny",
          },
          {
            id: "Jennifer",
            name: "詹妮弗",
            gender: "female",
            languages: ["en-US", "en-GB", "zh-CN"],
            accent: "en-US",
            note: "cinematic",
          },
          {
            id: "Rocky",
            name: "粤语-阿强",
            gender: "male",
            languages: ["en-US", "en-GB"],
            accent: null,
            note: "Cantonese",
          },
        ],
      },
    });
    api.mockImplementation(async (path: string) =>
      path === "/tenant/routes" ? [...ROUTES, tts] : undefined,
    );
    show("tts", [{ ...RELAY, name: "qwen" }]);

    await userEvent.click(await screen.findByRole("button", { name: "Edit order" }));
    await userEvent.click(screen.getByLabelText("American voice of model 1"));
    const american = await screen.findAllByRole("option");
    expect(american.map((o) => o.textContent)).toEqual([
      "Jennifer詹妮弗 · female · American · cinematic",
      "Cherry芊悦 · female · sunny",
      "Rocky粤语-阿强 · male · Cantonese",
    ]);
    await userEvent.keyboard("{Escape}");

    // A dialect voice isn't offered for Chinese; typing filters by who they are too.
    const chinese = screen.getByLabelText("Chinese voice of model 1");
    await userEvent.click(chinese);
    const ids = (await screen.findAllByRole("option")).map((o) => o.textContent?.slice(0, 6));
    expect(ids).toEqual(["Cherry", "Jennif"]);
    await userEvent.type(chinese, "詹妮");
    expect(await screen.findAllByRole("option")).toHaveLength(1);
  });

  it("says a member's task runs on their main account's models (ADR 0031 §5)", async () => {
    api.mockImplementation(async (path: string) =>
      path === "/tenant/routes"
        ? [route({ task: "chat", effective: ["school:gpt-x"], effective_source: "auto", provided_by: "Riverside School" })]
        : undefined,
    );
    show("chat");

    expect(await screen.findByTestId("route-source-chat")).toHaveTextContent("Provided by Riverside School");
    expect(screen.getByRole("list", { name: "Chat model" })).toHaveTextContent("school:gpt-x");
    // The main account's connections aren't this tenant's: not marked missing.
    expect(screen.queryByText("Connection deleted")).not.toBeInTheDocument();
  });

  it("says when the quota from the main account is used up", async () => {
    api.mockImplementation(async (path: string) =>
      path === "/tenant/routes"
        ? [route({ task: "chat", provided_by: "Riverside School", quota_exhausted: true })]
        : undefined,
    );
    show("chat");

    expect(await screen.findByText(/Your quota from Riverside School for this is used up/)).toBeInTheDocument();
  });
});
