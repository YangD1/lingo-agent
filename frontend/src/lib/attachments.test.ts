// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { compressImage, fitWithin, guessKind, uploadAttachment } from "./attachments";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fitWithin", () => {
  it("scales the long edge down to the limit, keeping the aspect ratio", () => {
    expect(fitWithin(4000, 3000)).toEqual({ width: 1600, height: 1200 });
    expect(fitWithin(1000, 3000)).toEqual({ width: 533, height: 1600 });
  });

  it("never scales up", () => {
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 });
  });
});

describe("guessKind", () => {
  it("goes by the declared type", () => {
    expect(guessKind({ type: "image/png" })).toBe("image");
    expect(guessKind({ type: "audio/webm" })).toBe("audio");
    expect(guessKind({ type: "application/pdf" })).toBe("document");
    expect(guessKind({ type: "" })).toBe("document");
  });
});

describe("compressImage", () => {
  it("keeps files it can't or shouldn't re-encode", async () => {
    const gif = new File(["GIF89a"], "a.gif", { type: "image/gif" });
    const pdf = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    expect(await compressImage(gif)).toBe(gif);
    expect(await compressImage(pdf)).toBe(pdf);
    // No createImageBitmap here (like a browser that can't decode HEIC): sent as is.
    const heic = new File(["x"], "a.heic", { type: "image/heic" });
    expect(await compressImage(heic)).toBe(heic);
  });
});

describe("uploadAttachment", () => {
  it("posts the file as multipart without forcing a content type", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ id: "a1" }), { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    expect(await uploadAttachment("c1", file)).toEqual({ id: "a1" });

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/conversations/c1/attachments");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined(); // fetch sets the multipart boundary itself
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("surfaces the backend's error code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: { code: "unsupported_file_type", message: "nope" } }),
            { status: 415 },
          ),
      ),
    );

    await expect(uploadAttachment("c1", new File(["x"], "x.exe"))).rejects.toMatchObject({
      status: 415,
      code: "unsupported_file_type",
    } satisfies Partial<ApiError>);
  });
});
