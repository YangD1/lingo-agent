import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Attachment } from "@/lib/types";

import en from "../../../messages/en.json";
import { MessageAttachments } from "./message-attachments";

const base: Attachment = {
  id: "a1",
  conversation_id: "c1",
  kind: "image",
  mime_type: "image/jpeg",
  filename: "worksheet.jpg",
  size_bytes: 200_000,
  status: "ready",
  text: "reading",
  meta: {},
  error: null,
  sent: true,
  created_at: "",
};

function show(attachments: Attachment[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <MessageAttachments attachments={attachments} />
    </NextIntlClientProvider>,
  );
}

describe("MessageAttachments", () => {
  it("shows images, voice messages and documents from the content endpoint", () => {
    const { container } = show([
      base,
      { ...base, id: "a2", kind: "audio", mime_type: "audio/webm", filename: "voice.webm" },
      {
        ...base,
        id: "a3",
        kind: "document",
        mime_type: "application/pdf",
        filename: "essay.pdf",
        size_bytes: 3 * 1048576,
        meta: { truncated: true },
      },
    ]);

    const image = screen.getByRole("img", { name: "worksheet.jpg" });
    expect(image).toHaveAttribute("src", "/api/attachments/a1/content");
    expect(image.closest("a")).toHaveAttribute("target", "_blank");
    expect(container.querySelector("audio")).toHaveAttribute("src", "/api/attachments/a2/content");
    const doc = screen.getByRole("link", { name: /essay\.pdf/ });
    expect(doc).toHaveAttribute("download", "essay.pdf");
    expect(doc).toHaveTextContent("3.0 MB · only the beginning was read");
  });
});
