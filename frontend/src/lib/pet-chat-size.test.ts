import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_CHAT_SIZE, fitChatSize, keepChatSize, MIN_CHAT_SIZE, readChatSize } from "./pet-chat-size";

describe("fitChatSize", () => {
  const roomy = { width: 1920, height: 1080 };

  it("keeps a size that fits", () => {
    expect(fitChatSize({ width: 600, height: 800 }, roomy)).toEqual({ width: 600, height: 800 });
  });

  it("goes no smaller than the minimum", () => {
    expect(fitChatSize({ width: 100, height: 100 }, roomy)).toEqual(MIN_CHAT_SIZE);
  });

  it("stays clear of the pet's side and the top and bottom", () => {
    expect(fitChatSize({ width: 5000, height: 5000 }, roomy)).toEqual({ width: 1920 - 128, height: 1080 - 32 });
  });

  it("fits a screen smaller than the minimum", () => {
    expect(fitChatSize(DEFAULT_CHAT_SIZE, { width: 400, height: 300 })).toEqual({ width: 272, height: 268 });
  });
});

describe("the kept size", () => {
  afterEach(() => window.localStorage.clear());

  it("is none until one is chosen", () => {
    expect(readChatSize()).toBeNull();
  });

  it("is read back, and forgotten for the default", () => {
    keepChatSize({ width: 500, height: 600 });
    expect(readChatSize()).toEqual({ width: 500, height: 600 });
    keepChatSize(null);
    expect(readChatSize()).toBeNull();
  });

  it("is none when what was kept is broken", () => {
    window.localStorage.setItem("lingo.tutorPet.chatSize", "{oops");
    expect(readChatSize()).toBeNull();
    window.localStorage.setItem("lingo.tutorPet.chatSize", JSON.stringify({ width: -1, height: "x" }));
    expect(readChatSize()).toBeNull();
  });
});
