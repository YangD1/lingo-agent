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
  samples: 0,
  source: "default",
  model: null,
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
    expect(screen.getByRole("button", { name: /Uses AI/ })).toHaveTextContent("AI");
    expect(api).not.toHaveBeenCalled();
  });

  it("shows each call when tapped: now and in the background, history or default", async () => {
    api.mockResolvedValue(estimates);
    show("chat_message");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));

    const details = await screen.findByTestId("ai-badge-details");
    expect(details).toHaveTextContent("Your tutor's reply is written by an AI model");
    expect(await screen.findByText("Reply")).toBeInTheDocument();
    expect(details).toHaveTextContent("≈ 2,310 input + 300 output tokens");
    expect(details).toHaveTextContent("average of your last 12 calls · model deepseek:deepseek-chat");
    expect(details).toHaveTextContent("Review the turn · in the background, after the reply");
    expect(details).toHaveTextContent("no history yet, default estimate · no model configured");
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

  it("says so when the estimate can't be loaded", async () => {
    api.mockRejectedValue(new Error("offline"));
    show("advice");
    await userEvent.click(screen.getByRole("button", { name: /Uses AI/ }));
    expect(await screen.findByText("Couldn't load the estimate.")).toBeInTheDocument();
    expect(screen.getByTestId("ai-badge-details")).toHaveTextContent("Today's advice is written");
  });
});
