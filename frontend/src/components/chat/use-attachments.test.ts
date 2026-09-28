import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Attachment } from "@/lib/types";

import { useAttachments } from "./use-attachments";

const lib = vi.hoisted(() => ({
  uploadAttachment: vi.fn(),
  getAttachment: vi.fn(),
  deleteAttachment: vi.fn(),
  retryAttachment: vi.fn(),
  updateAttachmentText: vi.fn(),
  compressImage: vi.fn(async (file: File) => file),
}));
vi.mock("@/lib/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/attachments")>()),
  ...lib,
}));

const attachment = (overrides: Partial<Attachment> = {}): Attachment => ({
  id: "a1",
  conversation_id: "c1",
  kind: "document",
  mime_type: "text/plain",
  filename: "notes.txt",
  size_bytes: 5,
  status: "ready",
  text: "hello",
  meta: {},
  error: null,
  sent: false,
  created_at: "",
  ...overrides,
});

const file = (name: string, type: string) => new File(["x"], name, { type });

function setup(conversationId: string | null = "c1") {
  const ensureConversation = vi.fn(async () => "new");
  const hook = renderHook(({ id }: { id: string | null }) => useAttachments(id, ensureConversation), {
    initialProps: { id: conversationId },
  });
  return { ...hook, ensureConversation };
}

beforeEach(() => {
  Object.values(lib).forEach((fn) => fn.mockReset());
  lib.compressImage.mockImplementation(async (f: File) => f);
  lib.deleteAttachment.mockResolvedValue(undefined);
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

describe("useAttachments", () => {
  it("uploads, polls while processing, and allows sending once ready", async () => {
    lib.uploadAttachment.mockResolvedValue(attachment({ status: "processing", text: null }));
    lib.getAttachment
      .mockResolvedValueOnce(
        attachment({ status: "processing", text: null, meta: { progress: { done: 1, total: 2 } } }),
      )
      .mockResolvedValue(attachment());
    const { result } = setup();

    act(() => result.current.add([file("notes.txt", "text/plain")]));

    expect(result.current.pending).toBe(true);
    await waitFor(() => expect(result.current.items[0].attachment?.status).toBe("ready"), {
      timeout: 4000,
    });
    expect(result.current.pending).toBe(false);
    expect(lib.uploadAttachment).toHaveBeenCalledWith("c1", expect.any(File));
    expect(lib.getAttachment).toHaveBeenCalledWith("a1");
  });

  it("creates the conversation once for the first files of a new chat", async () => {
    lib.uploadAttachment
      .mockResolvedValueOnce(attachment({ id: "a1" }))
      .mockResolvedValueOnce(attachment({ id: "a2" }));
    const { result, rerender, ensureConversation } = setup(null);
    // Like the page: the switch to the new conversation happens while it is being created.
    ensureConversation.mockImplementation(async () => {
      rerender({ id: "new" });
      await Promise.resolve();
      return "new";
    });

    await act(async () => {
      result.current.add([file("a.txt", "text/plain"), file("b.txt", "text/plain")]);
    });

    await waitFor(() => expect(result.current.items.map((i) => i.attachment?.id)).toEqual(["a1", "a2"]));
    expect(ensureConversation).toHaveBeenCalledOnce();
    expect(lib.uploadAttachment.mock.calls.map((c) => c[0])).toEqual(["new", "new"]);
  });

  it("drops the tray when the learner switches to another conversation", async () => {
    lib.uploadAttachment.mockResolvedValue(attachment());
    const { result, rerender } = setup("c1");
    act(() => result.current.add([file("a.txt", "text/plain")]));
    await waitFor(() => expect(result.current.items[0].attachment).not.toBeNull());

    rerender({ id: "c2" });

    expect(result.current.items).toEqual([]);
  });

  it("refuses more than 4 images and 5 files", () => {
    lib.uploadAttachment.mockReturnValue(new Promise(() => {}));
    const { result } = setup();

    act(() => result.current.add(Array.from({ length: 5 }, (_, i) => file(`${i}.png`, "image/png"))));
    expect(result.current.items).toHaveLength(4);
    expect(result.current.problem).toBe("too_many_images");

    act(() => result.current.add([file("a.pdf", "application/pdf"), file("b.pdf", "application/pdf")]));
    expect(result.current.items).toHaveLength(5);
    expect(result.current.problem).toBe("too_many_attachments");
  });

  it("keeps a failed upload so it can be retried", async () => {
    lib.uploadAttachment
      .mockRejectedValueOnce(new ApiError(0, "network_error", "offline"))
      .mockResolvedValueOnce(attachment());
    const { result } = setup();
    act(() => result.current.add([file("a.txt", "text/plain")]));
    await waitFor(() => expect(result.current.items[0].error?.code).toBe("network_error"));
    expect(result.current.pending).toBe(true);

    await act(() => result.current.retry(result.current.items[0].key));

    expect(result.current.items[0].error).toBeNull();
    expect(result.current.items[0].attachment?.id).toBe("a1");
  });

  it("deletes a removed file on the server", async () => {
    lib.uploadAttachment.mockResolvedValue(attachment());
    const { result } = setup();
    act(() => result.current.add([file("a.txt", "text/plain")]));
    await waitFor(() => expect(result.current.items[0].attachment).not.toBeNull());

    act(() => result.current.remove(result.current.items[0].key));

    expect(result.current.items).toEqual([]);
    expect(lib.deleteAttachment).toHaveBeenCalledWith("a1");
  });

  it("hands the files to a message and takes them back if it was refused", async () => {
    lib.uploadAttachment.mockResolvedValue(attachment());
    const { result } = setup();
    act(() => result.current.add([file("a.txt", "text/plain")]));
    await waitFor(() => expect(result.current.items[0].attachment).not.toBeNull());

    let taken: ReturnType<typeof result.current.take> = [];
    act(() => {
      taken = result.current.take();
    });
    expect(result.current.items).toEqual([]);
    act(() => result.current.restore(taken));

    expect(result.current.items.map((i) => i.attachment?.id)).toEqual(["a1"]);
    expect(lib.deleteAttachment).not.toHaveBeenCalled();
  });
});
