import { describe, expect, it } from "vitest";

import { ended, fromHistory, splitReply, started, stoppedWhileWriting, withToken, writing } from "./follow-ups";

describe("follow-ups", () => {
  it("splits a saved reply at each follow-up", () => {
    const content = "Short.\n\nPart one.\n\nPart two.";
    const followUps = fromHistory([
      { index: 1, outcome: "done", offset: 8 },
      { index: 2, outcome: "timeout", offset: 19 },
    ]);
    expect(splitReply(content, followUps).map((p) => [p.followUp?.index ?? 0, p.text])).toEqual([
      [0, "Short."],
      [1, "Part one."],
      [2, "Part two."],
    ]);
    expect(splitReply("Just this.", fromHistory([]))).toEqual([{ followUp: null, text: "Just this." }]);
  });

  it("marks where a streamed follow-up starts, after the separator", () => {
    let content = "Short.";
    let followUps = started(undefined, 1, 1000);
    expect(writing(followUps)?.index).toBe(1);
    // Nothing yet: an empty part under its heading.
    expect(splitReply(content, followUps).map((p) => p.text)).toEqual(["Short.", ""]);

    for (const token of ["\n\n", "It links ", "the past."]) {
      followUps = withToken(followUps, content, token)!;
      content += token;
    }
    expect(followUps[0].offset).toBe("Short.\n\n".length);
    followUps = ended(followUps, 1, "done")!;
    expect(writing(followUps)).toBeUndefined();
    expect(splitReply(content, followUps).map((p) => p.text)).toEqual(["Short.", "It links the past."]);
  });

  it("tokens of the reply itself leave follow-ups alone", () => {
    expect(withToken(undefined, "Sho", "rt.")).toBeUndefined();
    const done = ended(started(undefined, 1, 0), 1, "no_start");
    expect(withToken(done, "Short.", "more")).toBe(done);
  });

  it("stopping drops the follow-up being written and keeps the reply", () => {
    const content = "Short.\n\nHalf of it";
    const followUps = [{ index: 1, offset: 8, state: "writing" as const, startedAt: 0 }];
    const stopped = stoppedWhileWriting(content, followUps);
    expect(stopped.content).toBe("Short.");
    expect(stopped.followUps).toEqual([{ index: 1, offset: null, state: "ended", outcome: "stopped", startedAt: 0 }]);
    // Stopped before its first word: only the separator goes.
    const early = stoppedWhileWriting("Short.\n\n", [{ index: 1, offset: null, state: "writing" }]);
    expect(early.content).toBe("Short.");
  });
});
