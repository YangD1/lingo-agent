import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Memory } from "@/lib/types";

import zh from "../../../messages/zh-CN.json";
import { MemoryListSection } from "./memory-list-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

function fact(
  id: string,
  content: string,
  status: Memory["status"] = "active",
  by: string | null = null,
): Memory {
  return {
    id,
    kind: "fact",
    content,
    source_conversation_id: null,
    source_title: null,
    status,
    superseded_by_id: by,
    created_at: "2026-10-17T08:00:00Z",
    updated_at: "2026-10-17T08:00:00Z",
  };
}

const WEEK = fact("week", "下周有面试");
const MONTH = fact("month", "下个月有面试", "superseded", "week");
const JAZZ = fact("jazz", "喜欢爵士乐", "superseded");

async function show(memories: Memory[]) {
  api.mockResolvedValueOnce(memories);
  render(
    <NextIntlClientProvider locale="zh-CN" messages={zh}>
      <MemoryListSection kind="fact" />
    </NextIntlClientProvider>,
  );
  expect(api).toHaveBeenCalledWith("/memories?kind=fact&include_superseded=true");
  return screen.findByRole("button", { name: /已被替代/ });
}

beforeEach(() => api.mockReset());

describe("MemoryListSection facts", () => {
  it("folds what a fact replaced under it and the superseded ones at the bottom", async () => {
    const toggle = await show([WEEK, MONTH, JAZZ]);
    const current = screen.getByRole("list", { name: "助手记住的事" });
    expect(within(current).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText("下个月有面试")).not.toBeInTheDocument();

    await userEvent.click(within(current).getByRole("button", { name: "之前的说法（1）" }));
    expect(within(current).getByText("下个月有面试")).toBeInTheDocument();

    expect(toggle).toHaveTextContent("已被替代（2）");
    await userEvent.click(toggle);
    const old = screen.getByRole("list", { name: "已被替代（2）" });
    expect(within(old).getByText("已改成：下周有面试")).toBeInTheDocument();
    expect(within(old).getByText("助手删掉了这条")).toBeInTheDocument();
  });

  it("restores a dropped fact into the list", async () => {
    await userEvent.click(await show([WEEK, MONTH, JAZZ]));
    api.mockResolvedValueOnce({ ...JAZZ, status: "active", updated_at: "2026-10-17T09:00:00Z" });

    const old = screen.getByRole("list", { name: "已被替代（2）" });
    const row = within(old).getByText("喜欢爵士乐").closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "恢复" }));

    expect(api).toHaveBeenLastCalledWith("/memories/jazz/restore", { method: "POST" });
    const current = screen.getByRole("list", { name: "助手记住的事" });
    expect(within(current).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("喜欢爵士乐"),
      expect.stringContaining("下周有面试"),
    ]);
    expect(screen.getByRole("button", { name: /已被替代/ })).toHaveTextContent("已被替代（1）");
  });

  it("deleting a fact takes its earlier versions; the dropped ones stay", async () => {
    await show([WEEK, MONTH, JAZZ]);
    api.mockResolvedValueOnce(undefined);

    const current = screen.getByRole("list", { name: "助手记住的事" });
    await userEvent.click(within(current).getByRole("button", { name: "删除" }));
    await userEvent.click(within(current).getByRole("button", { name: "删除" }));

    expect(api).toHaveBeenLastCalledWith("/memories/week", { method: "DELETE" });
    expect(screen.getByText(/还没有/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /已被替代/ })).toHaveTextContent("已被替代（1）");
  });

  it("shows no superseded section when nothing was replaced", async () => {
    api.mockResolvedValueOnce([WEEK]);
    render(
      <NextIntlClientProvider locale="zh-CN" messages={zh}>
        <MemoryListSection kind="fact" />
      </NextIntlClientProvider>,
    );
    expect(await screen.findByText("下周有面试")).toBeInTheDocument();
    expect(screen.queryByTestId("memories-superseded")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /之前的说法/ })).not.toBeInTheDocument();
  });
});
