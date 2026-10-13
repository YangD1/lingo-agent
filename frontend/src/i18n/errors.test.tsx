import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import zh from "../../messages/zh-CN.json";
import { useErrorMessage } from "./errors";

function describeWith(locale: "en" | "zh-CN", messages: typeof en) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
  return renderHook(() => useErrorMessage(), { wrapper }).result.current;
}

describe("useErrorMessage", () => {
  it("translates known codes and falls back to the backend's message", () => {
    const message = describeWith("en", en);
    expect(message({ code: "email_taken", message: "x" })).toBe("This email is already registered.");
    expect(message({ code: "something_new", message: "Raw text" })).toBe("Raw text");
    const zhMessage = describeWith("zh-CN", zh as typeof en);
    expect(zhMessage({ code: "email_taken", message: "x" })).toBe("这个邮箱已经注册过了。");
    expect(zhMessage({ code: "brand_new_code", message: "raw english" })).toBe("raw english");
  });

  it("says how many seconds to wait when rate limited", () => {
    const error = { code: "rate_limited", message: "too many requests", retryAfter: 42 };
    expect(describeWith("en", en)(error)).toBe("Too many requests. Try again in 42 s.");
    expect(describeWith("zh-CN", zh as typeof en)(error)).toBe("操作太频繁，请 42 秒后再试。");
    expect(describeWith("en", en)({ ...error, retryAfter: null })).toMatch(/in 1 s/);
  });
});
