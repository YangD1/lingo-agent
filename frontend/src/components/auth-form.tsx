"use client";

import { CircleAlertIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/i18n/errors";
import { api, ApiError } from "@/lib/api";
import { safeNextPath } from "@/lib/auth";
import type { User } from "@/lib/types";

type Mode = "login" | "register";

export function AuthForm({ mode, next }: { mode: Mode; next?: string }) {
  const t = useTranslations("auth");
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = {
      email: String(form.get("email")),
      password: String(form.get("password")),
      ...(mode === "register" && { display_name: String(form.get("display_name")) || null }),
    };
    setPending(true);
    setError(null);
    try {
      await api<User>(`/auth/${mode}`, { method: "POST", json: body });
      router.replace(safeNextPath(next));
      router.refresh();
    } catch (e) {
      setError(errorMessage(e instanceof ApiError ? e : new ApiError(0, "network_error", "")));
      setPending(false);
    }
  }

  return (
    <div className="w-full max-w-[400px] rounded-2xl border bg-card p-5 md:p-[22px]">
      <LogoMark className="size-9" />
      <h1 className="mt-3 text-[22px] font-bold tracking-tight">{t(`${mode}.title`)}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t(`${mode}.description`)}</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="email">{t("email")}</Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            aria-invalid={error ? true : undefined}
            required
          />
        </div>
        {mode === "register" && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="display_name">{t("displayName")}</Label>
            <Input id="display_name" name="display_name" autoComplete="nickname" maxLength={100} />
          </div>
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">{t("password")}</Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "register" ? 8 : undefined}
            maxLength={128}
            aria-invalid={error ? true : undefined}
            aria-describedby={mode === "register" ? "password-hint" : undefined}
            required
          />
          {mode === "register" && (
            <p id="password-hint" className="text-xs text-muted-foreground">
              {t("passwordHint")}
            </p>
          )}
        </div>
        {error && (
          <p role="alert" className="flex items-center gap-1.5 text-sm text-destructive">
            <CircleAlertIcon className="size-4 shrink-0" />
            {error}
          </p>
        )}
        <Button type="submit" size="lg" disabled={pending}>
          {t(`${mode}.submit`)}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          {t(`${mode}.switchPrompt`)}{" "}
          <Link
            href={mode === "login" ? "/register" : "/login"}
            className="text-primary underline-offset-4 hover:underline"
          >
            {t(`${mode}.switchLink`)}
          </Link>
        </p>
      </form>
    </div>
  );
}
