import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import zh from "../../messages/zh-CN.json";
import { matchAction, PET_ACTIONS, petAction, QUICK_ACTIONS } from "./pet-actions";

const id = (text: string) => matchAction(text)?.id ?? null;

describe("matchAction", () => {
  it("knows short commands in Chinese and English", () => {
    expect(id("我要背单词")).toBe("vocab_review");
    expect(id("背单词！")).toBe("vocab_review");
    expect(id("学点新词吧")).toBe(null); // not a phrase it knows: the tutor answers
    expect(id("我想学新单词")).toBe("vocab_learn");
    expect(id("Flashcards, please")).toBe("vocab_review");
    expect(id("let's do some grammar practice")).toBe("practice");
    expect(id("帮我配置模型")).toBe("setup_models");
    expect(id("配置 API Key")).toBe("setup_models");
    expect(id("Today's plan")).toBe("plan");
  });

  it("picks the longest phrase found", () => {
    expect(id("实时通话")).toBe("speaking_call");
    expect(id("实时通话设置")).toBe("setup_realtime");
    expect(id("背新词")).toBe("vocab_learn");
  });

  it("leaves questions and longer messages to the tutor", () => {
    expect(id("背单词有什么技巧")).toBe(null);
    expect(id("怎么背单词")).toBe(null);
    expect(id("可以背单词吗")).toBe(null);
    expect(id("how do I review words?")).toBe(null);
    expect(id("昨天我背单词的时候遇到了一个特别难记的词")).toBe(null);
    expect(id("I would like to review words with you after dinner today")).toBe(null);
    expect(id("")).toBe(null);
  });

  it("matches English phrases on word boundaries", () => {
    expect(id("newsletter")).toBe(null);
    expect(id("news")).toBe("reading");
  });
});

describe("PET_ACTIONS", () => {
  it("has unique ids, wording in both languages, and known quick actions", () => {
    const ids = PET_ACTIONS.map((a) => a.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const a of PET_ACTIONS) {
      for (const messages of [en, zh]) {
        const text = (messages.tutorPet.actions as Record<string, { label: string; ask: string }>)[a.id];
        expect(text?.label, a.id).toBeTruthy();
        expect(text?.ask, a.id).toBeTruthy();
      }
      // Chinese phrases are compared without spaces or punctuation, English ones lower case.
      for (const phrase of a.triggers.zh) expect(phrase).toMatch(/^[^\s\p{P}A-Z]+$/u);
      for (const phrase of a.triggers.en) expect(phrase).toBe(phrase.toLowerCase());
      if (a.opens === "setup") expect(a.href).toMatch(/^\/settings#/);
      if (a.opens === "overlay") expect(a.href).toMatch(/^\/vocab\/review/);
    }
    for (const quick of QUICK_ACTIONS) expect(petAction(quick).id).toBe(quick);
    // Every id in the type is in the list (the list is the source of the wording check).
    expect(ids).toHaveLength(25);
  });
});
