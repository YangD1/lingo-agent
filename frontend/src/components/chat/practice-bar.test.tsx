import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Conversation } from "@/lib/types";

import en from "../../../messages/en.json";
import zh from "../../../messages/zh-CN.json";
import { ConversationList } from "./conversation-list";
import { PracticeBar } from "./practice-bar";

const KC = { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" };

const conversation = (id: string, focus: Conversation["focus_kc"]): Conversation => ({
  id,
  title: focus ? `Practice: ${focus.name_en}` : "Music",
  created_at: "",
  updated_at: "",
  focus_kc: focus,
});

describe("practice conversations", () => {
  it("name the grammar point in the UI language, with its evidence a link away", () => {
    render(
      <NextIntlClientProvider locale="zh-CN" messages={zh}>
        <PracticeBar kc={KC} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByTestId("practice-bar")).toHaveTextContent("语法练习：第三人称单数 A1");
    expect(screen.getByRole("link", { name: "查看依据" })).toHaveAttribute(
      "href",
      "/learner?kc=g.third",
    );
  });

  it("are marked in the conversation list", () => {
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <ConversationList
          conversations={[conversation("p1", KC), conversation("c1", null)]}
          activeId={null}
          onSelect={() => {}}
          onNew={() => {}}
          onDelete={() => {}}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getAllByLabelText("Grammar practice")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Grammar practice.*Third person -s/ })).toBeVisible();
  });
});
