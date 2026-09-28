import { describe, expect, it } from "vitest";

import { pickRecordingFormat } from "./use-recorder";

describe("pickRecordingFormat", () => {
  it("prefers webm/opus (Chrome, Firefox)", () => {
    expect(pickRecordingFormat(() => true)).toEqual({
      mimeType: "audio/webm;codecs=opus",
      extension: "webm",
    });
  });

  it("falls back to mp4 (Safari)", () => {
    expect(pickRecordingFormat((t) => t === "audio/mp4")).toEqual({
      mimeType: "audio/mp4",
      extension: "m4a",
    });
  });

  it("returns null when nothing is supported", () => {
    expect(pickRecordingFormat(() => false)).toBeNull();
  });
});
