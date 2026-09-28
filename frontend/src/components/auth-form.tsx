"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>{t(`${mode}.title`)}</CardTitle>
        <CardDescription>{t(`${mode}.description`)}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">{t("email")}</Label>
            <Input id="email" name="email" type="email" autoComplete="email" required />
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
              required
            />
            {mode === "register" && (
              <p className="text-xs text-muted-foreground">{t("passwordHint")}</p>
            )}
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={pending}>
            {t(`${mode}.submit`)}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {t(`${mode}.switchPrompt`)}{" "}
            <Link
              href={mode === "login" ? "/register" : "/login"}
              className="text-foreground underline underline-offset-4"
            >
              {t(`${mode}.switchLink`)}
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
