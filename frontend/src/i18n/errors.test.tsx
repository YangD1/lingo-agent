import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import zhCN from "../../messages/zh-CN.json";
import { useErrorMessage } from "./errors";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="zh-CN" messages={zhCN}>
      {children}
    </NextIntlClientProvider>
  );
}

describe("useErrorMessage", () => {
  it("translates known backend codes", () => {
    const { result } = renderHook(() => useErrorMessage(), { wrapper });
    expect(result.current({ code: "email_taken", message: "email already registered" })).toBe(
      "这个邮箱已经注册过了。",
    );
  });

  it("falls back to the backend message for unknown codes", () => {
    const { result } = renderHook(() => useErrorMessage(), { wrapper });
    expect(result.current({ code: "brand_new_code", message: "raw english" })).toBe("raw english");
  });
});
