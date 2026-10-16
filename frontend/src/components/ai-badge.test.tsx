import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type CallEstimate, resetEstimatesCache } from "@/lib/ai-usage";

import en from "../../messages/en.json";
import zhCN from "../../messages/zh-CN.json";
import { AiBadge } from "./ai-badge";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const call = (overrides: Partial<CallEstimate>): CallEstimate => ({
  task: "chat",
  timing: "now",
  per: "call",
  input_tokens: 2500,
  output_tokens: 300,
  audio_seconds: null,
  characters: null,
  samples: 0,
  source: "default",
  model: null,
  provided_by: null,
  ...overrides,
});

const estimates = {
  window: 20,
  features: [
    {
      feature: "chat_message",
      calls: [
        call({ source: "history", samples: 12, input_tokens: 2310, model: "deepseek:deepseek-chat" }),
        call({ task: "reflect", timing: "background", input_tokens: 3000, output_tokens: 500 }),
      ],
    },
    {
      feature: "chat_audio",
      calls: [call({ task: "asr", audio_seconds: 10.5, source: "history", samples: 3 })],
    },
    { feature: "chat_image", calls: [call({ task: "vision", per: "image" })] },
    {
      feature: "quiz_card",
      calls: [call({ task: "exercise_critic", per: "item", input_tokens: 1200, output_tokens: 150 })],
    },
    {
      feature: "read_aloud",
      calls: [call({ task: "tts", characters: 60, model: "school:tts-1", provided_by: "Riverside School" })],
    },
    {
      feature: "realtime_call",
      calls: [call({ task: "realtime", per: "minute", input_tokens: 20000, output_tokens: 1000 })],
    },
  ],
};

function show(feature: Parameters<typeof AiBadge>[0]["feature"], locale: "en" | "zh-CN" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : zhCN}>
      <AiBadge feature={feature} />
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  api.mockReset();
  resetEstimatesCache();
});

describe("AiBadge", () => {
  it("does not fetch until it is opened", () => {
    show("chat_message");
    // A bare star: the name comes from aria-label, there is no visible text.
    expect(screen.getByRole("button", { name: /Uses AI/ })).toHaveTextContent("");
    expect(api).not.toHaveBeenCalled();
  });

  it("shows each call when tapped: now and in the background, history or default", async () => {
    api.mockResolvedValue(estimates);
    show("chat_message");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));

    const details = await screen.findByTestId("ai-badge-details");
    expect(details).toHaveTextContent("Your assistant's reply is written by an AI model");
    expect(await screen.findByText("Reply")).toBeInTheDocument();
    expect(details).toHaveTextContent("≈ 2,310 input + 300 output tokens");
    expect(details).toHaveTextContent("model deepseek:deepseek-chat");
    expect(details).toHaveTextContent("average of your last 12 calls");
    expect(screen.getByText("Review the turn")).toBeInTheDocument();
    expect(details).toHaveTextContent("in the background, after the reply");
    expect(details).toHaveTextContent("no model configured");
    expect(details).toHaveTextContent("no history yet, default estimate");
  });

  it("estimates speech-to-text by audio length and images per image", async () => {
    api.mockResolvedValue(estimates);
    show("chat_audio");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));
    expect(await screen.findByText(/≈ 10.5 s of audio/)).toBeInTheDocument();

    show("chat_image", "zh-CN");
    await userEvent.click(screen.getByRole("button", { name: /使用 AI/ }));
    expect(await screen.findByText(/约 2,500 输入 \+ 300 输出 token 每张图/)).toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(1); // the second badge reused the first request
  });

  it("estimates read-aloud by characters", async () => {
    api.mockResolvedValue(estimates);
    show("read_aloud", "zh-CN");
    await userEvent.click(screen.getByRole("button", { name: /使用 AI/ }));
    expect(await screen.findByText(/约 60 个字符（按字符计费/)).toBeInTheDocument();
    expect(screen.getByText("朗读")).toBeInTheDocument();
    // A member's call on their main account's model says whose quota it uses (ADR 0031 §8).
    expect(screen.getByText("由 Riverside School 提供：扣对方分给你的额度。")).toBeInTheDocument();
  });

  it("estimates a realtime call per minute", async () => {
    api.mockResolvedValue(estimates);
    show("realtime_call");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));
    expect(
      await screen.findByText(/≈ 20,000 input \+ 1,000 output tokens per minute/),
    ).toBeInTheDocument();
    expect(screen.getByText("realtime call")).toBeInTheDocument();
    expect(screen.getByTestId("ai-badge-details")).toHaveTextContent("costs several times");
    expect(screen.queryByText(/Provided by/)).not.toBeInTheDocument();
  });

  it("explains every feature behind one control", async () => {
    api.mockResolvedValue(estimates);
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <AiBadge feature={["chat_image", "chat_pdf"]} />
      </NextIntlClientProvider>,
    );
    await userEvent.click(screen.getByTestId("ai-badge-chat_image-chat_pdf"));
    const details = await screen.findByTestId("ai-badge-details");
    expect(details).toHaveTextContent("reads each image first");
    expect(details).toHaveTextContent("Scanned pages are read by an AI model");
    expect(await screen.findByText(/per image/)).toBeInTheDocument();
  });

  it("estimates a review per question", async () => {
    api.mockResolvedValue(estimates);
    show("quiz_card");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));
    expect(await screen.findByText(/≈ 1,200 input \+ 150 output tokens per question/)).toBeInTheDocument();
  });

  it("says so when the estimate can't be loaded", async () => {
    api.mockRejectedValue(new Error("offline"));
    show("memory_edit");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));
    expect(await screen.findByText("Couldn't load the estimate.")).toBeInTheDocument();
    expect(screen.getByTestId("ai-badge-details")).toHaveTextContent("turns it into a vector");
  });
});
